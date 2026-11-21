/**
 * Componente reutilizable de campo de contraseña con botón integrado
 * para mostrar u ocultar los caracteres capturados por el usuario.
 */
import { useState, type InputHTMLAttributes } from "react";
import { Eye, EyeOff } from "lucide-react";

/**
 * Propiedades aceptadas por el campo de contraseña; hereda todos los
 * atributos estándar de `<input>` excepto `type`, ya que este componente
 * lo controla internamente según el estado de visibilidad.
 */
type PropiedadesEntradaContrasena = Omit<InputHTMLAttributes<HTMLInputElement>, "type">;

/**
 * Renderiza un `<input>` controlado de tipo `password` o `text` acompañado
 * de un botón accesible para alternar la visibilidad del secreto.
 */
export function EntradaContrasena({
  className: claseAdicional = "",
  ...propiedadesEntrada
}: PropiedadesEntradaContrasena) {
  // Indica si el texto de la contraseña es visible actualmente en pantalla.
  const [esVisible, establecerEsVisible] = useState(false);

  return (
    <div className="relative">
      <input
        {...propiedadesEntrada}
        type={esVisible ? "text" : "password"}
        className={`${claseAdicional} pr-10`}
      />
      <button
        type="button"
        onClick={() => establecerEsVisible((estadoPrevio) => !estadoPrevio)}
        className="absolute inset-y-0 right-0 px-3 flex items-center text-slate-400 hover:text-slate-200 transition-colors"
        aria-label={esVisible ? "Ocultar contraseña" : "Mostrar contraseña"}
        title={esVisible ? "Ocultar contraseña" : "Mostrar contraseña"}
      >
        {esVisible ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
      </button>
    </div>
  );
}
