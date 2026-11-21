/**
 * Punto de entrada del árbol React de IdentIA.
 *
 * Monta el componente raíz `<Aplicacion />` dentro de `#root` utilizando `StrictMode`
 * para detectar efectos secundarios durante el desarrollo.
 */
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import { Aplicacion } from "./App";

const elementoRaiz = document.getElementById("root");
if (elementoRaiz) {
  createRoot(elementoRaiz).render(
    <StrictMode>
      <Aplicacion />
    </StrictMode>
  );
}
