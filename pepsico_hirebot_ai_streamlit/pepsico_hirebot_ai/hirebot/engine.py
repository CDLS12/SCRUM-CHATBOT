from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4


# ============================================================
# PepsiCo HireBot AI - Motor conversacional simple
# ============================================================
# Este motor NO depende de OpenAI ni de internet. Está hecho para
# que la demo funcione en clase de forma local, con reglas de negocio,
# memoria de sesión, captura de datos faltantes y validaciones.


FIELD_LABELS: Dict[str, str] = {
    "solicitante": "Nombre del manager solicitante",
    "area": "Área o departamento",
    "puesto": "Puesto a contratar",
    "seniority": "Nivel / seniority",
    "tipo_contrato": "Tipo de contrato",
    "modalidad": "Modalidad de trabajo",
    "ubicacion": "Ubicación / sede",
    "salario_min": "Salario mínimo mensual MXN",
    "salario_max": "Salario máximo mensual MXN",
    "fecha_inicio": "Fecha deseada de inicio",
    "presupuesto_aprobado": "Presupuesto aprobado",
    "jefe_directo": "Jefe directo",
    "justificacion": "Justificación de la contratación",
    "hardware": "Hardware requerido",
    "accesos": "Accesos o sistemas requeridos",
}

# Orden de preguntas dinámicas. Esto implementa HU2: solicitar información faltante.
REQUIRED_FIELDS: List[str] = [
    "solicitante",
    "area",
    "puesto",
    "seniority",
    "tipo_contrato",
    "modalidad",
    "ubicacion",
    "salario_min",
    "salario_max",
    "fecha_inicio",
    "presupuesto_aprobado",
    "jefe_directo",
    "justificacion",
    "hardware",
    "accesos",
]

ALLOWED_AREAS = [
    "Recursos Humanos",
    "Finanzas",
    "Tecnología",
    "IT",
    "Ventas",
    "Operaciones",
    "Marketing",
    "Legal",
    "Supply Chain",
    "Data Analytics",
]
ALLOWED_MODALIDADES = ["presencial", "híbrido", "remoto"]
ALLOWED_CONTRATOS = ["tiempo completo", "medio tiempo", "temporal", "practicante", "internship"]
ALLOWED_SENIORITY = ["trainee", "junior", "semi senior", "senior", "lead", "manager"]
KNOWN_LOCATIONS = ["Monterrey", "CDMX", "Ciudad de México", "Guadalajara", "Puebla", "Querétaro", "Toluca", "Remoto"]
KNOWN_SYSTEMS = ["Correo", "Teams", "SAP", "VPN", "Power BI", "Workday", "SharePoint", "Azure", "GitHub", "Tableau"]
KNOWN_HARDWARE = ["Laptop", "Monitor", "Mouse", "Teclado", "Headset", "Celular", "Docking station"]


@dataclass
class BotState:
    active: bool = False
    draft: Dict[str, Any] = field(default_factory=dict)
    awaiting_field: Optional[str] = None
    ready_to_submit: bool = False
    last_request_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "active": self.active,
            "draft": self.draft,
            "awaiting_field": self.awaiting_field,
            "ready_to_submit": self.ready_to_submit,
            "last_request_id": self.last_request_id,
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "BotState":
        if not data:
            return cls()
        return cls(
            active=data.get("active", False),
            draft=data.get("draft", {}) or {},
            awaiting_field=data.get("awaiting_field"),
            ready_to_submit=data.get("ready_to_submit", False),
            last_request_id=data.get("last_request_id"),
        )


class HireBotEngine:
    def __init__(self, storage_path: str | Path = "data/solicitudes.json"):
        self.storage_path = Path(storage_path)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.storage_path.exists():
            self.storage_path.write_text("[]", encoding="utf-8")

    # ------------------------------------------------------------
    # Punto principal de conversación
    # ------------------------------------------------------------
    def reply(self, user_message: str, state: BotState) -> Tuple[str, BotState]:
        text = user_message.strip()
        low = normalize(text)

        if not text:
            return "Escribe una solicitud o usa el botón de demo para iniciar.", state

        if any(cmd in low for cmd in ["cancelar", "reiniciar", "borrar solicitud", "limpiar"]):
            return self._reset_response(), BotState()

        if any(cmd in low for cmd in ["ayuda", "que puedes hacer", "comandos"]):
            return self._help_response(), state

        if "demo" in low or "ejemplo" in low:
            state.active = True
            updates = self.demo_data()
            state.draft.update(updates)
            state.awaiting_field = None
            state.ready_to_submit = True
            return self._ready_response(state), state

        if "resumen" in low or "ver solicitud" in low or "estado" in low:
            if not state.active and not state.draft:
                return "Todavía no hay una solicitud activa. Puedes escribir: `quiero contratar a un analista de datos`.", state
            return self._summary_response(state), state

        confirm_words = ["confirmo", "confirmar", "enviar", "crear solicitud", "guardar solicitud", "mandala", "mándala", "si, enviar", "sí, enviar"]
        if state.ready_to_submit and any(w in low for w in confirm_words):
            request_id = self._save_request(state.draft)
            state.last_request_id = request_id
            submitted_summary = self._submitted_response(request_id, state.draft)
            return submitted_summary, BotState(last_request_id=request_id)

        # HU1: detectar inicio de contratación por chat.
        if not state.active:
            if self._has_hiring_intent(low):
                state.active = True
                state.ready_to_submit = False
                state.awaiting_field = None
            else:
                return self._welcome_response(), state

        # Si el bot estaba esperando un campo concreto, intentamos interpretar
        # la respuesta como valor de ese campo.
        notes: List[str] = []
        parsed_focus = False
        if state.awaiting_field:
            parsed_value, note = self._parse_value_for_field(state.awaiting_field, text)
            if parsed_value is not None:
                if isinstance(parsed_value, dict):
                    state.draft.update(parsed_value)
                else:
                    state.draft[state.awaiting_field] = parsed_value
                notes.append(note or f"Registré {FIELD_LABELS[state.awaiting_field]}.")
                state.awaiting_field = None
                parsed_focus = True

        # Si el usuario respondió una pregunta específica, no sobre-interpretamos
        # el mismo texto para evitar sobreescrituras accidentales. Si no había
        # pregunta pendiente, sí extraemos todos los datos posibles del mensaje.
        if not parsed_focus:
            updates, extraction_notes = self._extract_fields(text)
            for key, value in updates.items():
                if value not in [None, "", []]:
                    state.draft[key] = value
            notes.extend(extraction_notes)

        # Validaciones críticas HU3.
        validation_errors, validation_warnings = self._validate(state.draft)
        invalid_field = self._first_invalid_field(validation_errors)
        if invalid_field and self._all_required_present(state.draft):
            state.awaiting_field = invalid_field
            state.ready_to_submit = False
            return self._validation_error_response(validation_errors, validation_warnings, invalid_field), state

        missing = self._missing_fields(state.draft)
        if missing:
            next_field = missing[0]
            state.awaiting_field = next_field
            state.ready_to_submit = False
            return self._ask_next_question(next_field, state.draft, notes, validation_warnings), state

        if validation_errors:
            invalid_field = self._first_invalid_field(validation_errors) or REQUIRED_FIELDS[0]
            state.awaiting_field = invalid_field
            state.ready_to_submit = False
            return self._validation_error_response(validation_errors, validation_warnings, invalid_field), state

        state.ready_to_submit = True
        state.awaiting_field = None
        return self._ready_response(state, notes, validation_warnings), state

    # ------------------------------------------------------------
    # Extracción de campos desde texto libre
    # ------------------------------------------------------------
    def _extract_fields(self, text: str) -> Tuple[Dict[str, Any], List[str]]:
        updates: Dict[str, Any] = {}
        notes: List[str] = []
        raw = text.strip()
        low = normalize(raw)

        # Manager solicitante
        m = re.search(r"(?:soy|mi nombre es|manager solicitante(?: es)?|solicitante(?: es)?)\s+([a-záéíóúñü .'-]{3,60})", raw, re.I)
        if m:
            updates["solicitante"] = clean_name(m.group(1))

        # Área / departamento
        area = self._find_allowed_area(raw)
        if area:
            updates["area"] = area

        m = re.search(r"(?:area|área|departamento|depto)\s*(?:es|:|de)?\s*([a-záéíóúñü &]+?)(?=,|\.| con | para | en modalidad | modalidad | salario | sueldo |$)", raw, re.I)
        if m and not updates.get("area"):
            updates["area"] = clean_text(m.group(1))

        # Puesto
        m = re.search(r"\b(?:puesto|vacante|posicion|posición|rol)\b\s*(?:de|es|:)?\s*([a-záéíóúñü0-9 /+-]+?)(?=,|\.| con | para | en modalidad | modalidad | salario | sueldo | ubicaci[oó]n | sede | fecha |$)", raw, re.I)
        if m:
            updates["puesto"] = clean_text(m.group(1))
        else:
            m = re.search(r"(?:contratar|incorporar|abrir|solicitar)\s+(?:a\s+)?(?:un|una|el|la)?\s*([a-záéíóúñü0-9 /+-]+?)(?=,|\.| con | para | en | salario | sueldo |$)", raw, re.I)
            if m:
                candidate = clean_text(m.group(1))
                if len(candidate.split()) <= 7 and not any(x in normalize(candidate) for x in ["contratacion", "solicitud"]):
                    updates["puesto"] = candidate

        # Seniority
        for seniority in ALLOWED_SENIORITY:
            if normalize(seniority) in low:
                updates["seniority"] = "Semi Senior" if seniority == "semi senior" else seniority.title()
                break

        # Tipo de contrato
        for contrato in ALLOWED_CONTRATOS:
            if normalize(contrato) in low:
                updates["tipo_contrato"] = contrato
                break
        if "tiempo completo" not in low and any(x in low for x in ["full time", "full-time", "planta"]):
            updates["tipo_contrato"] = "tiempo completo"
        if any(x in low for x in ["medio tiempo", "part time", "part-time"]):
            updates["tipo_contrato"] = "medio tiempo"

        # Modalidad
        if "hibrido" in low or "híbrido" in raw.lower():
            updates["modalidad"] = "híbrido"
        elif "remoto" in low or "remote" in low:
            updates["modalidad"] = "remoto"
        elif "presencial" in low:
            updates["modalidad"] = "presencial"

        # Ubicación
        location = self._find_known_location(raw)
        if location:
            updates["ubicacion"] = location
        m = re.search(r"(?:ubicacion|ubicación|sede|ciudad|localidad)\s*(?:es|:|en|de)?\s*([a-záéíóúñü .]+?)(?=,|\.| modalidad | con | salario | sueldo | fecha |$)", raw, re.I)
        if m:
            updates["ubicacion"] = clean_text(m.group(1))

        # Salario / sueldo
        salary_update = self._extract_salary(raw)
        if salary_update:
            updates.update(salary_update)

        # Fecha de inicio
        parsed_date = self._extract_date(raw)
        if parsed_date:
            updates["fecha_inicio"] = parsed_date.isoformat()

        # Presupuesto aprobado
        if any(x in low for x in ["presupuesto aprobado", "budget aprobado", "aprobado por finanzas"]):
            if any(x in low for x in [" no ", "no esta", "no está", "sin presupuesto", "pendiente"]):
                updates["presupuesto_aprobado"] = False
            else:
                updates["presupuesto_aprobado"] = True
        elif "sin presupuesto" in low or "presupuesto pendiente" in low:
            updates["presupuesto_aprobado"] = False

        # Jefe directo
        m = re.search(r"(?:jefe directo|reporta a|manager directo|líder|lider)\s*(?:es|:|a)?\s*([a-záéíóúñü .'-]{3,60})", raw, re.I)
        if m:
            updates["jefe_directo"] = clean_name(m.group(1))

        # Justificación
        m = re.search(r"(?:justificacion|justificación|motivo|razon|razón|porque|por qué)\s*(?:es|:)?\s*([a-záéíóúñü0-9 ,.;'-]{10,180})", raw, re.I)
        if m:
            updates["justificacion"] = clean_text(m.group(1))
        elif any(x in low for x in ["reemplazo", "expansion", "expansión", "crecimiento", "nueva posicion", "nueva posición"]):
            # Toma la oración completa como justificación si no hay etiqueta explícita.
            updates["justificacion"] = clean_text(raw)

        # Hardware y accesos
        hardware = self._find_items(raw, KNOWN_HARDWARE)
        if hardware:
            updates["hardware"] = hardware
        systems = self._find_items(raw, KNOWN_SYSTEMS)
        if systems:
            updates["accesos"] = systems

        if updates:
            notes.append("Actualicé la solicitud con los datos que detecté en tu mensaje.")
        return updates, notes

    def _parse_value_for_field(self, field_name: str, text: str) -> Tuple[Any, str]:
        low = normalize(text)

        if field_name in ["solicitante", "jefe_directo"]:
            return clean_name(text), f"Registré {FIELD_LABELS[field_name]}: {clean_name(text)}."

        if field_name == "justificacion":
            value = clean_text(text)
            return value, f"Registré {FIELD_LABELS[field_name]}: {value}."

        if field_name in ["puesto", "area", "ubicacion", "seniority", "tipo_contrato", "modalidad"]:
            # Intentamos extracción específica primero, pero sin anteponer etiquetas
            # largas que puedan confundir los patrones.
            updates, _ = self._extract_fields(text)
            if updates.get(field_name) is not None:
                return updates[field_name], f"Registré {FIELD_LABELS[field_name]}: {updates[field_name]}."
            value = clean_text(text)
            if field_name == "modalidad":
                if "hibrido" in low:
                    value = "híbrido"
                elif "remoto" in low:
                    value = "remoto"
                elif "presencial" in low:
                    value = "presencial"
            return value, f"Registré {FIELD_LABELS[field_name]}: {value}."

        if field_name in ["salario_min", "salario_max"]:
            salary_update = self._extract_salary(text)
            if salary_update:
                return salary_update, "Registré el rango salarial."
            money = parse_money(text)
            if money is not None:
                return int(money), f"Registré {FIELD_LABELS[field_name]}: ${int(money):,} MXN."
            return None, "No pude leer el salario."

        if field_name == "fecha_inicio":
            d = self._extract_date(text)
            if d:
                return d.isoformat(), f"Registré fecha de inicio: {format_date(d)}."
            return None, "No pude leer la fecha."

        if field_name == "presupuesto_aprobado":
            if any(x in low for x in ["si", "sí", "aprobado", "autorizado", "claro"]):
                return True, "Registré que el presupuesto está aprobado."
            if any(x in low for x in ["no", "pendiente", "sin"]):
                return False, "Registré que el presupuesto no está aprobado."
            return None, "Responde sí o no."

        if field_name == "hardware":
            items = self._find_items(text, KNOWN_HARDWARE)
            if not items:
                items = split_items(text)
            return items, f"Registré hardware: {', '.join(items)}."

        if field_name == "accesos":
            items = self._find_items(text, KNOWN_SYSTEMS)
            if not items:
                items = split_items(text)
            return items, f"Registré accesos: {', '.join(items)}."

        return clean_text(text), f"Registré {FIELD_LABELS.get(field_name, field_name)}."

    # ------------------------------------------------------------
    # Validaciones y reglas de negocio
    # ------------------------------------------------------------
    def _validate(self, draft: Dict[str, Any]) -> Tuple[List[str], List[str]]:
        errors: List[str] = []
        warnings: List[str] = []

        min_salary = safe_int(draft.get("salario_min"))
        max_salary = safe_int(draft.get("salario_max"))
        if min_salary is not None and min_salary < 8000:
            errors.append("El salario mínimo debe ser mayor o igual a $8,000 MXN mensuales.")
        if max_salary is not None and max_salary > 250000:
            warnings.append("El salario máximo es alto; Finanzas debería revisarlo.")
        if min_salary is not None and max_salary is not None and min_salary > max_salary:
            errors.append("El salario mínimo no puede ser mayor que el salario máximo.")

        if draft.get("fecha_inicio"):
            try:
                d = date.fromisoformat(str(draft["fecha_inicio"]))
                if d < date.today():
                    errors.append("La fecha de inicio no puede estar en el pasado.")
                if d < date.today() + timedelta(days=7):
                    warnings.append("La fecha de inicio está muy cercana; IT y RH podrían requerir validación urgente.")
            except ValueError:
                errors.append("La fecha de inicio debe tener un formato válido, por ejemplo 15/07/2026.")

        if draft.get("modalidad") and normalize(str(draft["modalidad"])) not in [normalize(x) for x in ALLOWED_MODALIDADES]:
            errors.append("La modalidad debe ser presencial, híbrido o remoto.")

        if draft.get("tipo_contrato") and normalize(str(draft["tipo_contrato"])) not in [normalize(x) for x in ALLOWED_CONTRATOS]:
            warnings.append("El tipo de contrato no está en el catálogo base; RH deberá confirmarlo.")

        if draft.get("presupuesto_aprobado") is False:
            warnings.append("El presupuesto aparece como no aprobado; la solicitud se puede preparar, pero requerirá validación de Finanzas.")

        just = str(draft.get("justificacion", "")).strip()
        if just and len(just) < 10:
            errors.append("La justificación debe ser más descriptiva, por ejemplo: 'reemplazo por baja del analista anterior'.")

        # Regla práctica: si es remoto/híbrido y no trae laptop, sugerimos agregarla.
        modality = normalize(str(draft.get("modalidad", "")))
        hardware = [normalize(x) for x in draft.get("hardware", [])] if isinstance(draft.get("hardware"), list) else []
        if modality in ["remoto", "hibrido"] and hardware and "laptop" not in hardware:
            warnings.append("Para modalidad remota o híbrida normalmente se recomienda incluir Laptop.")

        return errors, warnings

    def _first_invalid_field(self, errors: List[str]) -> Optional[str]:
        joined = normalize(" ".join(errors))
        if "salario" in joined:
            return "salario_min"
        if "fecha" in joined:
            return "fecha_inicio"
        if "modalidad" in joined:
            return "modalidad"
        if "justificacion" in joined:
            return "justificacion"
        return None

    def _missing_fields(self, draft: Dict[str, Any]) -> List[str]:
        missing: List[str] = []
        for field_name in REQUIRED_FIELDS:
            value = draft.get(field_name)
            if value is None or value == "" or value == []:
                missing.append(field_name)
        return missing

    def _all_required_present(self, draft: Dict[str, Any]) -> bool:
        return len(self._missing_fields(draft)) == 0

    # ------------------------------------------------------------
    # Respuestas conversacionales
    # ------------------------------------------------------------
    def _welcome_response(self) -> str:
        return (
            "Hola, soy **PepsiCo HireBot AI**. Puedo ayudarte a iniciar una solicitud de contratación por chat.\n\n"
            "Para comenzar escribe algo como:\n"
            "> Quiero contratar a un Analista de Datos para el área de Data Analytics en Monterrey.\n\n"
            "También puedes escribir `demo` para cargar un ejemplo completo."
        )

    def _reset_response(self) -> str:
        return "Listo, cancelé la solicitud actual. Cuando quieras iniciar otra, escribe: `quiero iniciar una contratación`."

    def _help_response(self) -> str:
        return (
            "Puedo hacer esto:\n\n"
            "1. **Iniciar contratación mediante chat**.\n"
            "2. **Detectar información faltante** y hacer preguntas dinámicas.\n"
            "3. **Validar datos** como salario, fecha, modalidad y presupuesto.\n"
            "4. **Generar un folio de solicitud** para la demo.\n\n"
            "Comandos útiles: `demo`, `resumen`, `confirmar`, `cancelar`."
        )

    def _summary_response(self, state: BotState) -> str:
        missing = self._missing_fields(state.draft)
        errors, warnings = self._validate(state.draft)
        status = "Lista para confirmar" if not missing and not errors else "En captura"
        return (
            f"### Resumen de solicitud — {status}\n"
            f"{self._render_summary_table(state.draft)}\n\n"
            f"**Campos faltantes:** {', '.join(FIELD_LABELS[x] for x in missing) if missing else 'Ninguno'}\n\n"
            f"{render_issues('Errores', errors)}"
            f"{render_issues('Advertencias', warnings)}"
        )

    def _ask_next_question(self, field_name: str, draft: Dict[str, Any], notes: List[str], warnings: List[str]) -> str:
        progress = self._progress_text(draft)
        prefix = "\n".join(f"✅ {n}" for n in unique(notes))
        if prefix:
            prefix += "\n\n"
        warning_text = render_issues("Advertencias", warnings)
        question = self._question_for_field(field_name)
        return f"{prefix}{progress}\n\n{warning_text}**Me falta un dato:** {FIELD_LABELS[field_name]}.\n\n{question}"

    def _validation_error_response(self, errors: List[str], warnings: List[str], invalid_field: str) -> str:
        return (
            f"Encontré un problema de validación antes de continuar:\n\n"
            f"{render_issues('Errores', errors)}"
            f"{render_issues('Advertencias', warnings)}"
            f"Por favor corrige: **{FIELD_LABELS.get(invalid_field, invalid_field)}**.\n\n"
            f"{self._question_for_field(invalid_field)}"
        )

    def _ready_response(self, state: BotState, notes: Optional[List[str]] = None, warnings: Optional[List[str]] = None) -> str:
        notes = notes or []
        warnings = warnings or []
        prefix = "\n".join(f"✅ {n}" for n in unique(notes))
        if prefix:
            prefix += "\n\n"
        return (
            f"{prefix}La solicitud ya tiene la información mínima para enviarse.\n\n"
            f"### Resumen final\n"
            f"{self._render_summary_table(state.draft)}\n\n"
            f"{render_issues('Advertencias', warnings)}"
            "Escribe **confirmar** para generar el folio, o escribe el nombre de un campo para corregirlo."
        )

    def _submitted_response(self, request_id: str, draft: Dict[str, Any]) -> str:
        return (
            f"✅ **Solicitud creada correctamente.**\n\n"
            f"**Folio:** `{request_id}`\n\n"
            f"El HireBot registró la solicitud y la dejó lista para revisión de RH, Finanzas e IT.\n\n"
            f"{self._render_summary_table(draft)}"
        )

    def _question_for_field(self, field_name: str) -> str:
        questions = {
            "solicitante": "¿Cuál es tu nombre como manager solicitante?",
            "area": "¿Para qué área o departamento es la vacante? Ejemplo: Data Analytics, Ventas, Finanzas, IT.",
            "puesto": "¿Cuál es el puesto a contratar? Ejemplo: Analista de Datos.",
            "seniority": "¿Qué nivel tendrá? Ejemplo: trainee, junior, semi senior, senior, lead o manager.",
            "tipo_contrato": "¿Qué tipo de contrato será? Ejemplo: tiempo completo, medio tiempo, temporal o practicante.",
            "modalidad": "¿La modalidad será presencial, híbrido o remoto?",
            "ubicacion": "¿En qué ciudad o sede trabajará? Ejemplo: Monterrey, CDMX, Guadalajara o Remoto.",
            "salario_min": "¿Cuál es el salario mínimo mensual en MXN? Puedes responder `30000` o `30k`.",
            "salario_max": "¿Cuál es el salario máximo mensual en MXN? También puedes dar un rango como `30000 a 45000`.",
            "fecha_inicio": "¿Cuál es la fecha deseada de inicio? Ejemplo: 15/07/2026.",
            "presupuesto_aprobado": "¿El presupuesto ya está aprobado? Responde sí o no.",
            "jefe_directo": "¿Quién será el jefe directo de la persona contratada?",
            "justificacion": "¿Cuál es la justificación de la contratación? Ejemplo: reemplazo por baja o crecimiento del equipo.",
            "hardware": "¿Qué hardware necesitará? Ejemplo: laptop, monitor, mouse y headset.",
            "accesos": "¿Qué accesos o sistemas requerirá? Ejemplo: correo, Teams, SAP, VPN, Power BI.",
        }
        return questions.get(field_name, f"Indica el valor para {FIELD_LABELS.get(field_name, field_name)}.")

    def _progress_text(self, draft: Dict[str, Any]) -> str:
        completed = len(REQUIRED_FIELDS) - len(self._missing_fields(draft))
        total = len(REQUIRED_FIELDS)
        return f"Avance de captura: **{completed}/{total} campos completos**."

    def _render_summary_table(self, draft: Dict[str, Any]) -> str:
        lines = ["| Campo | Valor |", "|---|---|"]
        for field_name in REQUIRED_FIELDS:
            value = draft.get(field_name)
            if field_name in ["salario_min", "salario_max"] and value not in [None, ""]:
                value = f"${int(value):,} MXN"
            elif field_name == "fecha_inicio" and value:
                try:
                    value = format_date(date.fromisoformat(str(value)))
                except Exception:
                    pass
            elif isinstance(value, bool):
                value = "Sí" if value else "No"
            elif isinstance(value, list):
                value = ", ".join(value)
            if value in [None, "", []]:
                value = "Pendiente"
            lines.append(f"| {FIELD_LABELS[field_name]} | {value} |")
        return "\n".join(lines)

    # ------------------------------------------------------------
    # Persistencia local para demo
    # ------------------------------------------------------------
    def _save_request(self, draft: Dict[str, Any]) -> str:
        request_id = f"HR-{datetime.now().strftime('%Y%m%d')}-{uuid4().hex[:6].upper()}"
        record = {
            "folio": request_id,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "status": "Pendiente de revisión RH/Finanzas/IT",
            "data": draft,
        }
        try:
            data = json.loads(self.storage_path.read_text(encoding="utf-8"))
        except Exception:
            data = []
        data.append(record)
        self.storage_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return request_id

    def list_requests(self) -> List[Dict[str, Any]]:
        try:
            return json.loads(self.storage_path.read_text(encoding="utf-8"))
        except Exception:
            return []

    # ------------------------------------------------------------
    # Utilidades de extracción
    # ------------------------------------------------------------
    def _has_hiring_intent(self, low: str) -> bool:
        return any(word in low for word in ["contratar", "contratacion", "contratación", "vacante", "puesto", "reclutamiento", "onboarding", "nuevo empleado", "nueva posicion", "nueva posición"])

    def _find_allowed_area(self, text: str) -> Optional[str]:
        low = normalize(text)
        for area in ALLOWED_AREAS:
            area_norm = normalize(area)
            # Para claves cortas como IT usamos límites de palabra;
            # así evitamos falsos positivos dentro de otras palabras.
            if len(area_norm) <= 3:
                if re.search(rf"\b{re.escape(area_norm)}\b", low):
                    return area
            elif area_norm in low:
                return area
        return None

    def _find_known_location(self, text: str) -> Optional[str]:
        low = normalize(text)
        for loc in KNOWN_LOCATIONS:
            if normalize(loc) in low:
                return loc
        return None

    def _find_items(self, text: str, catalog: List[str]) -> List[str]:
        low = normalize(text)
        found: List[str] = []
        for item in catalog:
            if normalize(item) in low:
                found.append(item)
        return unique(found)

    def _extract_salary(self, text: str) -> Dict[str, int]:
        low = normalize(text)
        result: Dict[str, int] = {}

        # Rango: 30000 a 45000, 30k-45k, $30,000 - $45,000
        m = re.search(r"(\$?\s*\d[\d,.]*\s*(?:k|mil|mxn|pesos)?)\s*(?:-|a|hasta)\s*(\$?\s*\d[\d,.]*\s*(?:k|mil|mxn|pesos)?)", text, re.I)
        if m:
            a = parse_money(m.group(1))
            b = parse_money(m.group(2))
            if a is not None and b is not None:
                result["salario_min"] = int(min(a, b))
                result["salario_max"] = int(max(a, b))
                return result

        # Salario mínimo / máximo explícito
        m = re.search(r"(?:salario minimo|salario mínimo|minimo|mínimo)\s*(?:de|es|:)?\s*(\$?\s*\d[\d,.]*\s*(?:k|mil|mxn|pesos)?)", text, re.I)
        if m:
            money = parse_money(m.group(1))
            if money is not None:
                result["salario_min"] = int(money)

        m = re.search(r"(?:salario maximo|salario máximo|maximo|máximo)\s*(?:de|es|:)?\s*(\$?\s*\d[\d,.]*\s*(?:k|mil|mxn|pesos)?)", text, re.I)
        if m:
            money = parse_money(m.group(1))
            if money is not None:
                result["salario_max"] = int(money)

        # Un solo salario: lo tomamos como máximo si el usuario dice presupuesto/sueldo/salario.
        if not result and any(x in low for x in ["salario", "sueldo", "rango", "presupuesto"]):
            money_values = [parse_money(x) for x in re.findall(r"\$?\s*\d[\d,.]*\s*(?:k|mil|mxn|pesos)?", text, re.I)]
            money_values = [x for x in money_values if x is not None]
            if len(money_values) == 1:
                val = int(money_values[0])
                result["salario_min"] = val
                result["salario_max"] = val
            elif len(money_values) >= 2:
                result["salario_min"] = int(min(money_values[0], money_values[1]))
                result["salario_max"] = int(max(money_values[0], money_values[1]))

        return result

    def _extract_date(self, text: str) -> Optional[date]:
        low = normalize(text)
        today = date.today()
        if "hoy" in low:
            return today
        if "manana" in low or "mañana" in text.lower():
            return today + timedelta(days=1)
        if "proxima semana" in low or "próxima semana" in text.lower():
            return today + timedelta(days=7)
        if "siguiente mes" in low or "proximo mes" in low or "próximo mes" in text.lower():
            month = today.month + 1
            year = today.year
            if month == 13:
                month = 1
                year += 1
            return date(year, month, min(today.day, 28))

        # dd/mm/yyyy, dd-mm-yyyy, yyyy-mm-dd
        patterns = [
            (r"(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})", "dmy"),
            (r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})", "ymd"),
        ]
        for pattern, fmt in patterns:
            m = re.search(pattern, text)
            if m:
                try:
                    if fmt == "dmy":
                        day, month, year = [int(x) for x in m.groups()]
                        if year < 100:
                            year += 2000
                    else:
                        year, month, day = [int(x) for x in m.groups()]
                    return date(year, month, day)
                except ValueError:
                    return None
        return None

    def demo_data(self) -> Dict[str, Any]:
        future = date.today() + timedelta(days=30)
        return {
            "solicitante": "Carlos Lozano",
            "area": "Data Analytics",
            "puesto": "Analista de Datos",
            "seniority": "Junior",
            "tipo_contrato": "tiempo completo",
            "modalidad": "híbrido",
            "ubicacion": "Monterrey",
            "salario_min": 30000,
            "salario_max": 45000,
            "fecha_inicio": future.isoformat(),
            "presupuesto_aprobado": True,
            "jefe_directo": "Ana Vasconcelos",
            "justificacion": "Crecimiento del equipo y necesidad de automatizar reportes de contratación.",
            "hardware": ["Laptop", "Monitor", "Headset"],
            "accesos": ["Correo", "Teams", "VPN", "Power BI", "SAP"],
        }


# ============================================================
# Helpers generales
# ============================================================

def normalize(value: str) -> str:
    value = str(value).lower().strip()
    value = unicodedata.normalize("NFD", value)
    value = "".join(ch for ch in value if unicodedata.category(ch) != "Mn")
    value = re.sub(r"\s+", " ", value)
    return value


def clean_text(value: str) -> str:
    value = re.sub(r"\s+", " ", str(value)).strip(" ,.;:-")
    return value[:1].upper() + value[1:] if value else value


def clean_name(value: str) -> str:
    words = clean_text(value).split()
    stop = {"en", "con", "para", "salario", "sueldo", "modalidad", "puesto"}
    cleaned: List[str] = []
    for w in words:
        if normalize(w) in stop:
            break
        cleaned.append(w)
    return " ".join(w.capitalize() for w in cleaned)


def parse_money(value: str) -> Optional[float]:
    if value is None:
        return None
    s = normalize(str(value))
    multiplier = 1
    if "k" in s or "mil" in s:
        multiplier = 1000
    s = s.replace("$", "").replace("mxn", "").replace("pesos", "").replace("mil", "").replace("k", "")
    s = s.replace(",", "").strip()
    try:
        number = float(s)
        # Si el usuario escribió 30 y también k/mil, se vuelve 30000.
        return number * multiplier
    except ValueError:
        return None


def safe_int(value: Any) -> Optional[int]:
    try:
        if value is None or value == "":
            return None
        return int(float(value))
    except Exception:
        return None


def split_items(text: str) -> List[str]:
    parts = re.split(r",| y |/|;|\n", text, flags=re.I)
    items = [clean_text(p) for p in parts if clean_text(p)]
    return unique(items)


def unique(items: List[Any]) -> List[Any]:
    seen = set()
    result = []
    for item in items:
        key = normalize(str(item))
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


def format_date(d: date) -> str:
    return d.strftime("%d/%m/%Y")


def render_issues(title: str, issues: List[str]) -> str:
    if not issues:
        return ""
    emoji = "❌" if title.lower().startswith("error") else "⚠️"
    lines = "\n".join(f"- {issue}" for issue in issues)
    return f"{emoji} **{title}:**\n{lines}\n\n"
