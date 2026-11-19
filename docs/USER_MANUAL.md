# Manual de Uso y Operación — IdentIA

Esta guía concentra las reglas operativas indispensables para obtener el máximo desempeño biométrico en **IdentIA** durante el registro de personas y la operación diaria en kiosco.

---

## 1. Regla de Oro de Iluminación (Registro vs. Kiosco)

Las pruebas de campo demostraron un principio crítico para la precisión del reconocimiento facial:

> **Nunca realices el registro (enrolamiento) de una persona a contraluz.**

### ¿Por qué es tan importante?

| Condición durante el registro | Reconocimiento posterior con buena luz | Reconocimiento posterior con poca luz o mayor distancia |
|---|---|---|
| **Iluminación frontal limpia (recomendada)** | **90% – 94%** de similitud | **60% – 68%** de similitud (muy por encima del umbral de `42%`) |
| **A contraluz** (ventana o foco detrás) | Baja a **60% – 80%** | Puede caer por debajo del umbral de coincidencia |

Cuando una persona se registra a contraluz, sus vectores biométricos base quedan contaminados por subexposición, pérdida de detalle y compensación artificial. Eso degrada el reconocimiento **incluso cuando después pase lista frente a una cámara bien iluminada**.

Por esta razón, **IdentIA bloquea automáticamente el contraluz y sombras laterales severas durante el enrolamiento**, pero sí permite y compensa el contraluz en el **Kiosco en vivo** para tolerar variaciones ambientales reales del día a día.

---

## 2. Requisitos de Entorno para la Estación de Registro

Al dar de alta alumnos o empleados en **Personas y Registro**:

1. **Fuente de luz frente al rostro:** Coloca a la persona de cara a una ventana con cortina difusora, lámpara o luz ambiental pareja.
2. **Sin fuentes brillantes detrás:** Evita ventanas abiertas, puertas hacia el exterior, reflectores o pantallas muy luminosas justo detrás de la persona.
3. **Sin sombras laterales duras:** Evita iluminar únicamente un lado del rostro dejando el otro en penumbra.
4. **Cámara limpia y a la altura del rostro:** Sitúa la webcam aproximadamente al nivel de los ojos a una distancia cómoda (~50–70 cm).

---

## 3. Cómo Realizar el Registro Guiado (6 Poses)

1. Da de alta a la persona en **Personas y Registro** confirmando su **consentimiento biométrico**.
2. Pulsa **Enrolar** y utiliza **Auto-captura guiada** (o captura manual paso a paso).
3. Realiza cada una de las **6 poses** manteniendo la postura ~1 segundo hasta completar `Estabilidad 2/2`:
   - **1. Frontal:** Mira directo y nivelado al centro de la cámara.
   - **2. Izquierda:** Gira suavemente la cabeza hacia tu izquierda manteniendo ambos ojos visibles.
   - **3. Derecha:** Gira suavemente la cabeza hacia tu derecha manteniendo ambos ojos visibles.
   - **4. Arriba:** Levanta ligeramente el mentón.
   - **5. Abajo:** Inclina suavemente la cabeza hacia abajo.
   - **6. Sonrisa:** Mira al frente y sonríe de forma natural.
4. Revisa las 6 miniaturas temporales en la cuadrícula inferior; si alguna salió borrosa o movida, pulsa **Repetir** en esa pose específica.
5. Cuando el progreso indique **6/6**, pulsa **Finalizar enrolamiento** para confirmar el cierre y liberar las vistas previas temporales en memoria.

---

## 4. Operación Diaria en Kiosco en Vivo

* El **Kiosco en vivo** está calibrado para tolerar menor luz, mayor distancia y contraluz moderado (mostrando el indicador `"Contraluz detectado · compensación activa"`).
* En modo **Empresa**, el kiosco alterna automáticamente entre **Entrada** y **Salida** respetando el tiempo de *cooldown* anti-duplicados.
* En modo **Escuela**, registra una única asistencia (**Presente**) por sesión calculando puntualidad o retardo según la tolerancia configurada.
* Si un usuario no logra ser reconocido por fallo extremo de cámara o iluminación, utiliza el **Registro Manual de Respaldo** en **Grupos y Sesiones**.
