# PepsiCo HireBot AI

Prototipo funcional de chatbot con interfaz web para el proyecto SCRUM.

## Qué hace

- HU1: Permite iniciar una solicitud de contratación mediante chat.
- HU2: Detecta información faltante y pregunta dinámicamente por cada campo.
- HU3: Valida datos críticos del puesto, salario, fecha, modalidad y presupuesto.
- HU4: Que cada solicitud de contratacion tenga un folio unico
- HU8: Recibir confirmacion del estado de mi solicitud.
- HU10: Validar datos de la solicitud antes de registrarla mediante una API.
- Guarda solicitudes localmente en `data/solicitudes.json`.

## Cómo correrlo

```bash
pip install -r requirements.txt
streamlit run app.py
```

Luego abre la liga local que aparece en la terminal, normalmente:

```text
http://localhost:8501
```

## Mensajes de prueba

Puedes escribir:

```text
Quiero contratar a un Analista de Datos para Data Analytics en Monterrey, modalidad híbrido, tiempo completo, salario 30000 a 45000, fecha 15/07/2026, presupuesto aprobado.
```

Después el bot preguntará lo que falte.

También puedes escribir:

```text
ejemplo
```

para cargar una solicitud completa.

## Comandos útiles

- `ejemplo`: carga una solicitud de ejemplo.
- `resumen`: muestra el avance de la solicitud.
- `confirmar`: guarda la solicitud y genera folio.
- `cancelar`: reinicia la conversación.

## Estructura

```text
pepsico_hirebot_ai/
├── app.py
├── requirements.txt
├── README.md
├── data/
│   └── solicitudes.json
└── hirebot/
    ├── __init__.py
    └── engine.py
```

## Notas para demo en clase

1. Abre la app con `streamlit run app.py`.
2. Presiona `Cargar ejemplo` para mostrar el flujo completo rápido.
3. Presiona `Resumen` para enseñar los campos capturados.
4. Presiona `Confirmar` para generar un folio tipo `HR-YYYYMMDD-XXXXXX`.
5. Muestra que el bot valida errores: prueba con un salario mínimo de `5000` o una fecha pasada.
