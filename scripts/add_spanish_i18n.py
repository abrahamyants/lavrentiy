"""
Add Spanish (es) translations to the I18N object in dashboard.html.

Strategy: each I18N entry is `key:{en:'X',ru:'Y'}`. We rewrite it as
`key:{en:'X',ru:'Y',es:'Z'}` using a hand-written translation map.

Idempotent: skips entries that already have an `es:` field.
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HTML = REPO / "dashboard.html"

# Spanish translations keyed by I18N key.
SPANISH = {
    # Boot
    "boot_sub": "MOTOR DE RECONSTRUCCIÓN DE VOZ",
    "conn_lost": "Conexión perdida",
    "conn_sub": "El motor Lavrentiy no está corriendo",
    # Sidebar sections
    "sec_tone": "Tono ",
    "sec_layer": "Capa",
    "sec_enhance": "Mejoras",
    "sec_mode": "Modo ",
    "sec_situation": "Situación",
    # Tones
    "tone_casual": "Casual",
    "tone_pro": "Profesional",
    "tone_friend": "Amigo",
    "tone_formal": "Formal",
    # Layers
    "layer1": "I. Transcribir", "layer1d": "texto crudo, sin limpieza",
    "layer2": "II. Reconstruir", "layer2d": "LLM + tono",
    "layer3": "III. Perfil", "layer3d": "+ vocabulario",
    "layer4": "IV. Disfluencia", "layer4d": "+ disfluencia",
    # Enhancement toggles
    "lbl_para": "Paralingüístico", "hint_para": "tos/risa",
    "lbl_transcribe": "Transcribir", "hint_transcribe": "insertar [etiquetas] en el texto",
    "lbl_prosodic": "Prosódico", "hint_prosodic": "tono/energía/ritmo",
    # Mode descs
    "mode_raw": "pegar tal cual", "mode_fast": "sin validación", "mode_safe": "+ verificación Falcon",
    # Situations
    "sit_default": "Predeterminada", "sit_default_d": "+ uso diario",
    "sit_stress": "Alto estrés", "sit_stress_d": "+ asistencia total",
    "sit_reading": "Lectura", "sit_reading_d": "+ casi fluido",
    # Engine panel
    "lbl_multitemp": "Multi-Temp", "lbl_prepseed": "Semilla Prep",
    "lbl_blocks": "Bloqueos", "lbl_redos_eng": "Repeticiones",
    "lbl_nospeech": "Sin Voz", "lbl_logprob": "LogProb Med.",
    "lbl_sensitive": "◄ sensible", "lbl_tolerant": "tolerante ►",
    "lbl_speech": "VOZ",
    "lbl_pause": "Ratio Pausa", "lbl_wpm_eng": "Palabras/Min",
    "lbl_sevmod": "Mod. Severidad", "lbl_para2": "Paralingüístico",
    "lbl_speaker": "Estado Hablante",
    "lbl_base": "base", "lbl_speech2": "voz",
    # Shortcuts
    "sec_shortcuts": "Atajos ",
    "hk_record": "Grabar", "hk_tone": "Cambiar Tono",
    "hk_layer": "Cambiar Capa", "hk_stats": "Estadísticas",
    "hk_quit": "Salir (×3)",
    "hk_press": "Pulse cualquier tecla...",
    "hk_save": "Guardar en motor",
    # Stats bar
    "sl_words": "Palabras", "sl_sessions": "Sesiones",
    "sl_wpm": "PPM", "sl_api": "Llamadas API",
    "sl_difficulty": "Dificultad Med.", "sl_cost": "Costo Est.",
    # Learn bar
    "ll_corrections": "Correcciones", "ll_fillers": "Muletillas",
    "ll_vocab": "Vocabulario", "ll_triggers": "Disparadores",
    "ll_editdist": "Dist. Edición", "ll_redos": "Repeticiones",
    "lp_next": "Próx. ciclo", "lp_decay": "Decaimiento",
    # Tabs
    "tab_console": "Consola", "tab_sessions": "Sesiones",
    "tab_learning": "Aprendizaje", "tab_insights": "Análisis",
    "tab_prep": "Preparar", "tab_calibrate": "Calibrar",
    "tab_tips": "Consejos", "tab_profile": "Perfil",
    # Tab empties & labels
    "console_empty": "Esperando entrada...",
    "learn_empty": "Aún no se han detectado patrones. Sigue hablando.",
    "learn_report": "📊 INFORME SEMANAL",
    "insights_empty": "Cambia a Capa 4 para ver análisis de disfluencia.",
    "insights_nodata": "Aún no hay datos suficientes. Sigue usando Capa 4.",
    "sessions_empty": "Empieza a dictar. Las sesiones aparecerán aquí.",
    # Insights section titles
    "phoneme_title": "MAPA DE DIFICULTAD DE FONEMAS",
    "covert_title": "PATRONES DE EVITACIÓN ENCUBIERTA",
    "onset_title": "ANOMALÍAS DE INICIO",
    "onset_sub": "(inicios que evitas)",
    "lang_onset_title": "PESOS DE INICIO POR IDIOMA",
    "fingerprint_title": "HUELLA DE SUSTITUCIÓN",
    "shadow_title": "DERIVA DE EVITACIÓN",
    "lowconf_title": "SEGMENTOS DE BAJA CONFIANZA",
    "lowconf_sub": "(última sesión — incertidumbre Whisper cerca de zonas de riesgo Brown)",
    "fluency_title": "TENDENCIA DE FLUIDEZ",
    "fl_pause": "PAUSA MED.", "fl_rate": "RITMO MED.",
    "fl_sev": "SEV+ MED.", "fl_sessions": "SESIONES",
    # Prep tab
    "prep_ph": "Pega tu guion, puntos clave o correo aquí. Lavrentiy señalará palabras donde podrías tartamudear y sugerirá alternativas más seguras.",
    "prep_btn": "PREPARAR", "prep_scanning": "ESCANEANDO...",
    "prep_safe": "SEGURO", "prep_risky": "RIESGOSO", "prep_trigger": "DISPARADOR CONOCIDO",
    "prep_seed": "⚡ WHISPER PREPARADO — el decodificador usará este texto como contexto",
    "prep_empty": "Escribe o pega lo que vas a decir. Pulsa PREPARAR para escanear.",
    "prep_nothing": "Nada que preparar.",
    "prep_analyzing": "Analizando texto y generando alternativas...",
    # Calibrate tab
    "cal_title": "CALIBRACIÓN WHISPER",
    "cal_sub": "Lee 60 frases en voz alta. Cada grabación se convierte en una muestra de entrenamiento para reconocimiento personalizado.",
    "cal_start": "INICIAR CALIBRACIÓN", "cal_resume": "REANUDAR CALIBRACIÓN",
    "cal_record": "GRABAR", "cal_stop": "PARAR", "cal_saving": "GUARDANDO...",
    "cal_skip": "SALTAR",
    "cal_instruction": "Lee esta frase en voz alta, naturalmente. No intentes ocultar la disfluencia.",
    "cal_complete": "CALIBRACIÓN COMPLETADA",
    "cal_wer_title": "Resumen WER de calibración",
    "aug_title": "AUMENTO DE DATOS",
    "aug_sub": "Genera voz disfluente sintética a partir de los datos de calibración vía TTS. Multiplica tu conjunto de entrenamiento 5x con repeticiones de palabras, repeticiones de frases e inserciones de interjecciones.",
    "aug_btn": "GENERAR DATOS AUMENTADOS",
    "aug_regen": "REGENERAR DATOS AUMENTADOS",
    "aug_generating": "GENERANDO...", "aug_starting": "INICIANDO...",
    "wer_title": "TENDENCIA WER",
    "wer_sub": "Tasa de error por palabra en sesiones recientes — menos es mejor. Muestra qué tan bien Whisper transcribe tu voz a lo largo del tiempo.",
    "wer_avg": "WER MED.", "wer_recent": "RECIENTE", "wer_samples": "MUESTRAS",
    # Profile (The File)
    "prof_triggers": "Palabras disparadoras", "prof_fillers": "Muletillas",
    "prof_vocab": "Vocabulario", "prof_corrections": "Correcciones",
    "prof_covert": "Pares de evitación encubierta",
    "prof_add_trigger": "Añadir disparador...",
    "prof_add_filler": "Añadir muletilla...",
    "prof_add_vocab": "Añadir término preferido...",
    "prof_heard": "Se oye como...",
    "prof_should": "Debería ser...",
    # Bottom
    "disclaimer": "“Лаврентий hace lo que puede. Revisa antes de enviar.”",
    # Profiles
    "prof_new_title": "Nuevo perfil",
    "prof_cancel": "Cancelar",
    "prof_create": "Crear",
    "prof_name_ph": "Nombre",
    # Dynamic states
    "st_idle": "inactivo", "st_recording": "grabando", "st_processing": "procesando", "st_command": "CMD",
    # Notes
    "note_select": "selecciona Reconstruir +",
    # Help overlay
    "help_title": "Guía", "help_sub": "MANUAL DE OPERACIONES",
    "help_search": "Buscar...",
    # Help sections (long bodies kept brief — focus on titles + subs; bodies left in EN/RU until manual review)
    "ha_layers": "Capas", "ha_layers_sub": "L1 Transcribir hasta L4 Disfluencia",
    "ha_layers_body": "<strong>L1 Transcribir</strong> — Solo Whisper. Voz a texto crudo, sin limpieza con IA. El más rápido.<br><strong>L2 Reconstruir</strong> — GPT reescribe usando tu tono. Quita muletillas, corrige gramática. ~1-2s más lento.<br><strong>L3 Perfil</strong> — Igual que L2 + tu vocabulario y mapa de correcciones personal.<br><strong>L4 Disfluencia</strong> — Modo clínico completo. Seguimiento de disfluencia, puntuación de exposición, reescrituras escaladas por severidad.<div class=\"ha-example\"><span class=\"he-in\">Dices:</span> \"Pues eh básicamente la la cosa es eh funcionando\"<br><span class=\"he-out\">L1:</span> \"Pues eh básicamente la la cosa es eh funcionando\"<br><span class=\"he-out\">L2:</span> \"La cosa funciona.\"</div>",
    "ha_tone": "Tono", "ha_tone_sub": "Cómo GPT reescribe tu voz (L2+)",
    "ha_tone_body": "<strong>Casual</strong> — Conversacional. Contracciones, palabras simples.<br><strong>Profesional</strong> — Listo para negocios. Lenguaje limpio y preciso.<br><strong>Amigo</strong> — Relajado. Como mensaje a un amigo.<br><strong>Formal</strong> — Académico/legal. Sin contracciones, preciso.<br><br>No afecta a L1 (se colapsa cuando se selecciona L1).",
    "ha_mode": "Modo", "ha_mode_sub": "Pasos del flujo: RAW, FAST, SAFE",
    "ha_mode_body": "<strong>RAW</strong> <code>pegar tal cual</code> — GPT corre para análisis pero pega el texto original de Whisper.<br><strong>FAST</strong> <code>sin validación</code> — GPT reescribe, confiamos, pegamos. Mejor velocidad/calidad.<br><strong>SAFE</strong> <code>+ verificación Falcon</code> — GPT reescribe, Falcon verifica que el significado se preserva. Más lento, más seguro.<br><br>Los tres producen salida idéntica en L1. Se colapsa cuando se selecciona L1.",
    "ha_enhance": "Mejoras", "ha_enhance_sub": "Análisis paralingüístico + prosódico",
    "ha_enhance_body": "<strong>Paralingüístico</strong> — Detecta tos, risa, suspiro, carraspeo, respiración, pausa. Independiente de la capa.<br>&nbsp;&nbsp;• <strong>Sub-toggle Transcribir:</strong> ON = etiquetas insertadas en el texto (<code>[Risa]</code>). OFF = solo registrado.<br><br><strong>Prosódico</strong> — Rastrea tono (F0), energía, ritmo. Alimenta el modificador de severidad en L4. Auto-activado en L4 y Alto Estrés.<div class=\"ha-example\"><span class=\"he-out\">Consola:</span> \"Voz: pause_ratio=47% rate=3.4syl/s → severity +0.4\"<br><span class=\"he-out\">Consola:</span> \"Prosódico: Tensión vocal (tono errático en 100%)\"</div>",
    "ha_situation": "Situación", "ha_situation_sub": "Presets del motor en un clic",
    "ha_situation_body": "<strong>Predeterminada</strong> — Dictado diario. Severidad 1.0. Sin auto-toggles.<br><strong>Alto Estrés</strong> — Teléfono, entrevista, presentación. Auto-activa L4, DAF 100ms, todos los toggles. Severidad 1.5.<br><strong>Lectura</strong> — Leer en voz alta. Casi fluido. Severidad 0.3, L3 ligero.",
    "ha_daf": "DAF", "ha_daf_sub": "Retroalimentación auditiva retardada para fluidez",
    "ha_daf_body": "Reproduce tu voz a través de auriculares con un ligero retraso. El retraso engaña al cerebro para que se ralentice, mejorando la fluidez. Independiente de todas las demás configuraciones.<br><br><strong>Toggle:</strong> ON/OFF &nbsp; <strong>Dial:</strong> Retraso en milisegundos (predeterminado 100ms). Más = efecto más fuerte.",
    "ha_whisper": "Diagnóstico Whisper", "ha_whisper_sub": "Multi-temp, bloqueos, confianza",
    "ha_whisper_body": "<strong>Multi-Temp</strong> — Ejecuta Whisper a múltiples temperaturas. Acuerdo = confiable. Desacuerdo = marcado. 3x más lento.<br><strong>Bloqueos</strong> — Bloqueos de voz detectados (Whisper alucinó sobre silencio).<br><strong>Slider Sin Voz</strong> — ◄ Sensible (atrapa más) vs. Tolerante ► (menos falsas alarmas). Predeterminado: 15%.<br><strong>LogProb Med.</strong> — Confianza de Whisper. Sobre <code>-0.4</code> = bueno. Bajo <code>-0.7</code> = adivinando.",
    "ha_stats": "Estadísticas y barras de aprendizaje", "ha_stats_sub": "Clicable — salta a pestañas de detalle",
    "ha_stats_body": "<strong>Palabras / Sesiones</strong> — Clic → pestaña Sesiones.<br><strong>Llamadas API / Costo Est.</strong> — Clic → pestaña Consola. Costo ~$0.0032/sesión.<br><strong>Correcciones</strong> — Auto-correcciones aprendidas (ej. Duncan → Dankeschön). Clic → pestaña Aprendizaje.<br><strong>Muletillas</strong> — Muletillas identificadas (eh, ah, tipo). Clic → pestaña Aprendizaje.<br><strong>Vocabulario</strong> — Términos preferidos en tu perfil. Clic → pestaña Aprendizaje.<br><strong>Disparadores</strong> — Palabras que causan bloqueos. Clic → pestaña Aprendizaje.",
    "ha_hotkeys": "Atajos", "ha_hotkeys_sub": "Accesos directos del teclado (reasignables)",
    "ha_hotkeys_body": "<span class=\"ha-kbd\">F9</span> Iniciar/parar grabación &nbsp;<span class=\"ha-kbd\">F10</span> Cambiar tonos &nbsp;<span class=\"ha-kbd\">F11</span> Cambiar capas &nbsp;<span class=\"ha-kbd\">F12</span> Estadísticas &nbsp;<span class=\"ha-kbd\">F3</span> ×3 Salir<br><br>Todos reasignables desde la sección Atajos al final de la barra lateral.",
    "ha_colors": "Colores de consola", "ha_colors_sub": "Qué significa el texto coloreado",
    "ha_colors_body": "<strong style=\"color:#222\">Blanco</strong> — Tu voz transcrita (con conteo de palabras)<br><strong style=\"color:#16a34a\">Verde</strong> — Estado del flujo, grabación, tiempo de pegado<br><strong style=\"color:#a16207\">Amarillo</strong> — Análisis de voz y diagnóstico Whisper<br><strong style=\"color:#dc2626\">Rojo</strong> — Alertas prosódicas (tensión vocal, tono errático)<br><strong style=\"color:#92400e\">Marrón</strong> — Sospecha de bloqueo (Whisper alucinó sobre silencio)",
    "ha_pipeline": "Cómo funciona", "ha_pipeline_sub": "Qué pasa cuando pulsas Grabar",
    "ha_pipeline_body": "<strong style=\"color:var(--red-bright)\">1. Hablas</strong><br>Tu voz se captura por el micrófono. El audio se limpia (ruido de fondo eliminado, volumen nivelado) antes de que cualquier otra cosa lo toque.<br><br><strong style=\"color:var(--red-bright)\">2. Whisper escucha</strong><br>Whisper de OpenAI convierte tu voz en texto. También reporta <em>qué tan seguro</em> está sobre cada palabra. Los momentos silenciosos (bloqueos, pausas) se marcan en lugar de adivinarse.<br><span style=\"opacity:0.6;font-size:0.9em\">Si usas Preparación de guion, tu texto previsto ayuda a Whisper a adivinar mejor — como darle la clave de respuestas.</span><br><br><strong style=\"color:var(--red-bright)\">3. Limpieza rápida</strong><br>Antes de que cualquier IA se involucre, las disfluencias obvias se eliminan automáticamente (costo cero, instantáneo):<br>• Sílabas repetidas: “p-p-pop” → “pop”<br>• Palabras repetidas: “Yo yo yo quiero” → “Yo quiero”<br>• Muletillas: “eh”, “ah”, “tipo”, “o sea”<br>• Falsos comienzos: “voy a— fui” → “fui”<br>• Prolongaciones: “mmmmaybe” → “maybe”<br><span style=\"opacity:0.6;font-size:0.9em\">Frases naturales como “adiós adiós” se conservan — gramática real, no disfluencias.</span><br><br><strong style=\"color:var(--red-bright)\">4. Depende de tu Capa:</strong><br><br><strong>Capa 1</strong> — Listo. El texto limpio se pega. Sin IA, sin costo más allá de la transcripción.<br><br><strong>Capa 2</strong> — GPT reescribe usando el tono que elegiste (casual, profesional, etc). Sabe que el texto vino de un micrófono, así que es indulgente con el desorden. No usa datos personales.<br><br><strong>Capa 3</strong> — Igual que L2, además GPT conoce <em>tus</em> palabras preferidas y correcciones aprendidas.<br><br><strong>Capa 4</strong> — El motor completo. Un modelo de IA más fuerte recibe un informe detallado:<br>• Qué sonidos son más difíciles para ti<br>• Palabras que tiendes a evitar e intercambiar<br>• Dónde Whisper estaba inseguro o detectó un bloqueo<br>• Eventos no verbales (toses, pausas) para que no invente palabras<br>• Tus patrones de tono, energía y ritmo<br><br><strong style=\"color:var(--red-bright)\">5. Verificación de seguridad</strong><br>En modo SAFE, una segunda IA lee tanto tus palabras originales como la reescritura, y pregunta: “¿Cambió el significado?” Si sí, la reescritura es rechazada y se usa tu texto original. Números, montos en dólares y porcentajes se verifican por separado.<br><br><strong style=\"color:var(--red-bright)\">6. Pegar</strong><br>El texto final va al portapapeles y se pega en cualquier app que estés usando.",
    "ha_tips": "Consejos", "ha_tips_sub": "Trucos para usuarios avanzados",
    "ha_tips_body": "• Pulsa el <strong>cronómetro</strong> en el anillo de estado para reiniciarlo.<br>• <strong>Toggle compacto</strong> (arriba a la izquierda) colapsa a una barra mínima con chips clicables.<br>• Tono y Modo se <strong>colapsan automáticamente</strong> en L1 (no tienen efecto).<br>• La situación <strong>Alto Estrés</strong> es un botón de pánico de un clic: L4 + DAF + todos los toggles.<br>• Pulsa cualquier <strong>celda de estadística/aprendizaje</strong> para saltar a la pestaña de detalle.",
}


# Match key:{en:'X',ru:'Y'} where ' inside is escaped as \'.
# Group 1: leading prefix incl. key
# Group 2: en value (no closing quote)
# Group 3: ru value (no closing quote)
ENTRY_RE = re.compile(
    r"(\b(\w+):\{en:'((?:\\'|[^'])*)',ru:'((?:\\'|[^'])*)')\}"
)


def add_spanish(html_text):
    seen_keys = []
    skipped_no_translation = []

    def replacer(match):
        full_prefix = match.group(1)  # e.g. "boot_sub:{en:'X',ru:'Y'"
        key = match.group(2)
        seen_keys.append(key)
        if key not in SPANISH:
            skipped_no_translation.append(key)
            return match.group(0)  # leave unchanged
        es_value = SPANISH[key].replace("'", "\\'")
        return f"{full_prefix},es:'{es_value}'}}"

    new_text = ENTRY_RE.sub(replacer, html_text)
    return new_text, seen_keys, skipped_no_translation


def main():
    text = HTML.read_text(encoding="utf-8")

    # Idempotency: if any I18N entry already has es:, abort to avoid doubling.
    if re.search(r"\{en:'[^']*',ru:'[^']*',es:", text):
        print("Already has es: entries — skipping (idempotent).")
        return

    new_text, seen_keys, skipped = add_spanish(text)
    print(f"Found {len(seen_keys)} I18N entries.")
    print(f"Translated: {len(seen_keys) - len(skipped)}")
    print(f"Skipped (no Spanish provided): {len(skipped)}")
    if skipped:
        for k in skipped:
            print(f"  - {k}")

    HTML.write_text(new_text, encoding="utf-8")
    print(f"\nWrote {HTML}")


if __name__ == "__main__":
    main()
