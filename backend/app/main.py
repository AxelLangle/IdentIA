from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import Base, SessionLocal, engine as default_engine, get_db
from app.models import FaceEmbedding, Group, Organization, Person, User
from app.routers import academic, attendance, auth, organizations, persons, security
from app.schemas import HealthResponse
from app.security import hash_secret
from app.vision.engine import BiometricEngine
from app.vision.models_loader import ensure_models


def seed_initial_data(db: Session) -> None:
    """Crea Superadmin, organización demo y administrador inicial si faltan."""
    settings = get_settings()

    superadmin = db.scalars(select(User).where(User.role == "superadmin")).first()
    if superadmin is None:
        superadmin = User(
            email=settings.bootstrap_superadmin_email.strip().lower(),
            full_name=settings.bootstrap_superadmin_name,
            password_hash=hash_secret(settings.bootstrap_superadmin_password),
            role="superadmin",
            organization_id=None,
        )
        db.add(superadmin)
        db.flush()

    existing_orgs = db.scalar(select(func.count(Organization.id))) or 0
    if existing_orgs == 0:
        org = Organization(
            name="IdentIA Demo — Empresa",
            mode="enterprise",
            late_tolerance_minutes=15,
            cooldown_seconds=60,
            store_avatar_by_default=True,
        )
        db.add(org)
        db.flush()

        db.add(
            Group(
                organization_id=org.id,
                name="General",
                code="GEN-01",
                schedule_start="09:00",
                schedule_end="18:00",
            )
        )

        org_admin_email = settings.bootstrap_org_admin_email.strip().lower()
        existing_admin = db.scalars(select(User).where(User.email == org_admin_email)).first()
        if existing_admin is None:
            db.add(
                User(
                    email=org_admin_email,
                    full_name="Administrador Empresa Demo",
                    password_hash=hash_secret(settings.bootstrap_org_admin_password),
                    role="org_admin",
                    organization_id=org.id,
                    created_by_user_id=superadmin.id,
                )
            )

    db.commit()


def create_app(
    biometric_engine: BiometricEngine | None = None,
    init_models: bool = True,
    db_engine=None,
    session_factory=None,
) -> FastAPI:
    settings = get_settings()
    active_engine = db_engine or default_engine
    active_session_factory = session_factory or SessionLocal

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        Base.metadata.create_all(bind=active_engine)
        with active_session_factory() as db:
            seed_initial_data(db)

        if biometric_engine is not None:
            app.state.biometric_engine = biometric_engine
        elif init_models:
            yunet_path, sface_path = ensure_models(settings.models_dir)
            app.state.biometric_engine = BiometricEngine(
                yunet_path=yunet_path,
                sface_path=sface_path,
                score_threshold=settings.yunet_score_threshold,
                nms_threshold=settings.yunet_nms_threshold,
            )
        else:
            app.state.biometric_engine = None
        yield

    application = FastAPI(
        title=settings.app_name,
        version="0.4.0",
        description="Motor biométrico y plataforma de asistencia multi-organización IdentIA.",
        lifespan=lifespan,
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    application.include_router(auth.router)
    application.include_router(security.router)
    application.include_router(organizations.router)
    application.include_router(persons.router)
    application.include_router(attendance.router)
    application.include_router(academic.router)

    @application.get("/api/health", response_model=HealthResponse, tags=["system"])
    def health(db: Session = Depends(get_db)) -> HealthResponse:
        engine_ready = getattr(application.state, "biometric_engine", None) is not None
        orgs_count = db.scalar(select(func.count(Organization.id))) or 0
        persons_count = db.scalar(select(func.count(Person.id))) or 0
        embeddings_count = db.scalar(select(func.count(FaceEmbedding.id))) or 0
        return HealthResponse(
            status="ok",
            models_loaded=engine_ready,
            model_name=settings.model_name,
            model_version=settings.model_version,
            organizations_count=orgs_count,
            persons_count=persons_count,
            embeddings_count=embeddings_count,
        )

    return application


app = create_app()
