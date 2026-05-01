"""
Add Portuguese (pt) and French (fr) translations to the I18N object in dashboard.html.

Mirror of add_spanish_i18n.py — extends each entry with pt: and fr: fields.
Idempotent: skips entries that already have pt: or fr:.
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HTML = REPO / "dashboard.html"

PORTUGUESE = {
    "boot_sub": "MOTOR DE RECONSTRUÇÃO DE VOZ",
    "conn_lost": "Conexão perdida",
    "conn_sub": "O motor Lavrentiy não está rodando",
    "sec_tone": "Tom ", "sec_layer": "Camada", "sec_enhance": "Melhorias",
    "sec_mode": "Modo ", "sec_situation": "Situação",
    "tone_casual": "Casual", "tone_pro": "Profissional",
    "tone_friend": "Amigo", "tone_formal": "Formal",
    "layer1": "I. Transcrever", "layer1d": "texto bruto, sem limpeza",
    "layer2": "II. Reconstruir", "layer2d": "LLM + tom",
    "layer3": "III. Perfil", "layer3d": "+ vocabulário",
    "layer4": "IV. Disfluência", "layer4d": "+ disfluência",
    "lbl_para": "Paralinguístico", "hint_para": "tosse/risada",
    "lbl_transcribe": "Transcrever", "hint_transcribe": "inserir [tags] no texto",
    "lbl_prosodic": "Prosódico", "hint_prosodic": "tom/energia/ritmo",
    "mode_raw": "colar como está", "mode_fast": "sem validação", "mode_safe": "+ verificação Falcon",
    "sit_default": "Padrão", "sit_default_d": "+ uso diário",
    "sit_stress": "Alto Estresse", "sit_stress_d": "+ assistência total",
    "sit_reading": "Leitura", "sit_reading_d": "+ quase fluente",
    "lbl_multitemp": "Multi-Temp", "lbl_prepseed": "Semente Prep",
    "lbl_blocks": "Bloqueios", "lbl_redos_eng": "Repetições",
    "lbl_nospeech": "Sem Voz", "lbl_logprob": "LogProb Méd.",
    "lbl_sensitive": "◄ sensível", "lbl_tolerant": "tolerante ►",
    "lbl_speech": "VOZ",
    "lbl_pause": "Razão de Pausa", "lbl_wpm_eng": "Palavras/Min",
    "lbl_sevmod": "Mod. Severidade", "lbl_para2": "Paralinguístico",
    "lbl_speaker": "Estado do Falante",
    "lbl_base": "base", "lbl_speech2": "voz",
    "sec_shortcuts": "Atalhos ",
    "hk_record": "Gravar", "hk_tone": "Trocar Tom",
    "hk_layer": "Trocar Camada", "hk_stats": "Estatísticas",
    "hk_quit": "Sair (×3)",
    "hk_press": "Pressione qualquer tecla...",
    "hk_save": "Salvar no motor",
    "sl_words": "Palavras", "sl_sessions": "Sessões",
    "sl_wpm": "PPM", "sl_api": "Chamadas API",
    "sl_difficulty": "Dificuldade Méd.", "sl_cost": "Custo Est.",
    "ll_corrections": "Correções", "ll_fillers": "Muletas",
    "ll_vocab": "Vocabulário", "ll_triggers": "Gatilhos",
    "ll_editdist": "Dist. Edição", "ll_redos": "Repetições",
    "lp_next": "Próx. ciclo", "lp_decay": "Decaimento",
    "tab_console": "Console", "tab_sessions": "Sessões",
    "tab_learning": "Aprendizado", "tab_insights": "Análise",
    "tab_prep": "Preparar", "tab_calibrate": "Calibrar",
    "tab_tips": "Dicas", "tab_profile": "Perfil",
    "console_empty": "Aguardando entrada...",
    "learn_empty": "Nenhum padrão aprendido ainda. Continue falando.",
    "learn_report": "📊 RELATÓRIO SEMANAL",
    "insights_empty": "Mude para Camada 4 para ver análises de gagueira.",
    "insights_nodata": "Dados insuficientes ainda. Continue usando Camada 4.",
    "sessions_empty": "Comece a ditar. As sessões aparecerão aqui.",
    "phoneme_title": "MAPA DE DIFICULDADE DE FONEMAS",
    "covert_title": "PADRÕES DE EVITAÇÃO ENCOBERTA",
    "onset_title": "ANOMALIAS DE INÍCIO",
    "onset_sub": "(inícios que você evita)",
    "lang_onset_title": "PESOS DE INÍCIO POR IDIOMA",
    "fingerprint_title": "IMPRESSÃO DE SUBSTITUIÇÃO",
    "shadow_title": "DERIVA DE EVITAÇÃO",
    "lowconf_title": "SEGMENTOS DE BAIXA CONFIANÇA",
    "lowconf_sub": "(última sessão — incerteza Whisper perto das zonas de risco Brown)",
    "fluency_title": "TENDÊNCIA DE FLUÊNCIA",
    "fl_pause": "PAUSA MÉD.", "fl_rate": "RITMO MÉD.",
    "fl_sev": "SEV+ MÉD.", "fl_sessions": "SESSÕES",
    "prep_ph": "Cole seu roteiro, pontos de fala ou e-mail aqui. Lavrentiy vai marcar palavras onde você pode gaguejar e sugerir alternativas mais seguras.",
    "prep_btn": "PREPARAR", "prep_scanning": "ESCANEANDO...",
    "prep_safe": "SEGURO", "prep_risky": "RISCO", "prep_trigger": "GATILHO CONHECIDO",
    "prep_seed": "⚡ WHISPER PREPARADO — o decodificador usará este texto como contexto",
    "prep_empty": "Digite ou cole o que você vai dizer. Aperte PREPARAR para escanear.",
    "prep_nothing": "Nada para preparar.",
    "prep_analyzing": "Analisando texto e gerando alternativas...",
    "cal_title": "CALIBRAÇÃO WHISPER",
    "cal_sub": "Leia 60 frases em voz alta. Cada gravação se torna uma amostra de treinamento para reconhecimento personalizado.",
    "cal_start": "INICIAR CALIBRAÇÃO", "cal_resume": "CONTINUAR CALIBRAÇÃO",
    "cal_record": "GRAVAR", "cal_stop": "PARAR", "cal_saving": "SALVANDO...",
    "cal_skip": "PULAR",
    "cal_instruction": "Leia esta frase em voz alta, naturalmente. Não tente esconder a gagueira.",
    "cal_complete": "CALIBRAÇÃO COMPLETA",
    "cal_wer_title": "Resumo WER da calibração",
    "aug_title": "AUMENTO DE DADOS",
    "aug_sub": "Gera fala disfluente sintética dos dados de calibração via TTS. Multiplica seu conjunto de treinamento 5x com repetições de palavras, repetições de frases e inserções de interjeições.",
    "aug_btn": "GERAR DADOS AUMENTADOS",
    "aug_regen": "REGENERAR DADOS AUMENTADOS",
    "aug_generating": "GERANDO...", "aug_starting": "INICIANDO...",
    "wer_title": "TENDÊNCIA WER",
    "wer_sub": "Taxa de erro por palavra em sessões recentes — menor é melhor. Mostra quão bem o Whisper transcreve sua fala ao longo do tempo.",
    "wer_avg": "WER MÉD.", "wer_recent": "RECENTE", "wer_samples": "AMOSTRAS",
    "prof_triggers": "Palavras-gatilho", "prof_fillers": "Muletas",
    "prof_vocab": "Vocabulário", "prof_corrections": "Correções",
    "prof_covert": "Pares de evitação encoberta",
    "prof_add_trigger": "Adicionar gatilho...",
    "prof_add_filler": "Adicionar muleta...",
    "prof_add_vocab": "Adicionar termo preferido...",
    "prof_heard": "Ouvido como...",
    "prof_should": "Deveria ser...",
    "disclaimer": "“Лаврентий faz o melhor que pode. Verifique antes de enviar.”",
    "prof_new_title": "Novo perfil",
    "prof_cancel": "Cancelar",
    "prof_create": "Criar",
    "prof_name_ph": "Nome",
    "st_idle": "ocioso", "st_recording": "gravando", "st_processing": "processando", "st_command": "CMD",
    "note_select": "selecione Reconstruir +",
    "help_title": "Guia", "help_sub": "MANUAL DE OPERAÇÕES",
    "help_search": "Buscar...",
    "ha_layers": "Camadas", "ha_layers_sub": "L1 Transcrever até L4 Disfluência",
    "ha_layers_body": "<strong>L1 Transcrever</strong> — Apenas Whisper. Voz para texto bruto, sem limpeza por IA. Mais rápido.<br><strong>L2 Reconstruir</strong> — GPT reescreve usando seu tom. Remove muletas, corrige gramática. ~1-2s mais lento.<br><strong>L3 Perfil</strong> — Igual ao L2 + seu vocabulário pessoal e mapa de correções.<br><strong>L4 Disfluência</strong> — Modo clínico completo. Rastreamento de disfluência, pontuação de exposição, reescritas escaladas por severidade.",
    "ha_tone": "Tom", "ha_tone_sub": "Como GPT reescreve sua fala (L2+)",
    "ha_tone_body": "<strong>Casual</strong> — Conversacional. Contrações, palavras simples.<br><strong>Profissional</strong> — Pronto para negócios. Linguagem limpa e precisa.<br><strong>Amigo</strong> — Relaxado. Como mensagem para um amigo.<br><strong>Formal</strong> — Acadêmico/jurídico. Sem contrações, preciso.",
    "ha_mode": "Modo", "ha_mode_sub": "Etapas do pipeline: RAW, FAST, SAFE",
    "ha_mode_body": "<strong>RAW</strong> <code>colar como está</code> — GPT roda para análise mas cola o texto original do Whisper.<br><strong>FAST</strong> <code>sem validação</code> — GPT reescreve, confia, cola. Melhor velocidade/qualidade.<br><strong>SAFE</strong> <code>+ verificação Falcon</code> — GPT reescreve, Falcon verifica preservação de significado. Mais lento, mais seguro.",
    "ha_enhance": "Melhorias", "ha_enhance_sub": "Análise paralinguística + prosódica",
    "ha_enhance_body": "<strong>Paralinguística</strong> — Detecta tosse, risada, suspiro, pigarro, respiração, pausa. Independente da camada.<br>&nbsp;&nbsp;• <strong>Sub-toggle Transcrever:</strong> ON = tags inseridas no texto (<code>[Risada]</code>). OFF = só registrado.<br><br><strong>Prosódica</strong> — Rastreia tom (F0), energia, ritmo de fala. Alimenta modificador de severidade no L4.",
    "ha_situation": "Situação", "ha_situation_sub": "Predefinições do motor com um clique",
    "ha_situation_body": "<strong>Padrão</strong> — Ditado diário. Severidade 1.0. Sem auto-toggles.<br><strong>Alto Estresse</strong> — Telefone, entrevista, apresentação. Auto-ativa L4, DAF 100ms, todos os toggles. Severidade 1.5.<br><strong>Leitura</strong> — Leitura em voz alta. Quase fluente. Severidade 0.3, L3 leve.",
    "ha_daf": "DAF", "ha_daf_sub": "Retroalimentação Auditiva Atrasada para fluência",
    "ha_daf_body": "Reproduz sua voz pelos fones com um leve atraso. O atraso engana o cérebro para desacelerar, melhorando a fluência. Independente de todas as outras configurações.",
    "ha_whisper": "Diagnóstico Whisper", "ha_whisper_sub": "Multi-temp, bloqueios, confiança",
    "ha_whisper_body": "<strong>Multi-Temp</strong> — Roda Whisper em múltiplas temperaturas. Concordância = confiável. Discordância = marcado. 3x mais lento.<br><strong>Bloqueios</strong> — Bloqueios de fala detectados (Whisper alucinou sobre silêncio).",
    "ha_stats": "Estatísticas e barras de aprendizado", "ha_stats_sub": "Clicável — pula para abas de detalhe",
    "ha_stats_body": "<strong>Palavras / Sessões</strong> — Clique → aba Sessões.<br><strong>Chamadas API / Custo Est.</strong> — Clique → aba Console. Custo ~$0,0032/sessão.<br><strong>Correções</strong> — Auto-correções aprendidas. Clique → aba Aprendizado.",
    "ha_hotkeys": "Atalhos", "ha_hotkeys_sub": "Atalhos de teclado (reatribuíveis)",
    "ha_hotkeys_body": "<span class=\"ha-kbd\">F9</span> Iniciar/parar gravação &nbsp;<span class=\"ha-kbd\">F10</span> Trocar tons &nbsp;<span class=\"ha-kbd\">F11</span> Trocar camadas &nbsp;<span class=\"ha-kbd\">F12</span> Estatísticas &nbsp;<span class=\"ha-kbd\">F3</span> ×3 Sair",
    "ha_colors": "Cores do console", "ha_colors_sub": "O que o texto colorido significa",
    "ha_colors_body": "<strong style=\"color:#222\">Branco</strong> — Sua fala transcrita (com contagem de palavras)<br><strong style=\"color:#16a34a\">Verde</strong> — Status do pipeline, gravação, tempo de cola<br><strong style=\"color:#a16207\">Amarelo</strong> — Análise de fala e diagnóstico Whisper<br><strong style=\"color:#dc2626\">Vermelho</strong> — Alertas prosódicos<br><strong style=\"color:#92400e\">Marrom</strong> — Suspeita de bloqueio",
    "ha_pipeline": "Como funciona", "ha_pipeline_sub": "O que acontece quando você aperta Gravar",
    "ha_pipeline_body": "<strong>1.</strong> Você fala, áudio capturado.<br><strong>2.</strong> Whisper transcreve com confiança por palavra.<br><strong>3.</strong> Limpeza rápida (muletas, repetições).<br><strong>4.</strong> Camada escolhida processa.<br><strong>5.</strong> Verificação de segurança em SAFE.<br><strong>6.</strong> Cola no app aberto.",
    "ha_tips": "Dicas", "ha_tips_sub": "Truques para usuários avançados",
    "ha_tips_body": "• Clique no <strong>cronômetro</strong> no anel de status para reiniciar.<br>• <strong>Toggle compacto</strong> (canto superior esquerdo) colapsa para barra mínima.<br>• Tom e Modo <strong>auto-colapsam</strong> no L1 (sem efeito).<br>• <strong>Alto Estresse</strong> é o botão de pânico de um clique: L4 + DAF + todos os toggles.",
}

FRENCH = {
    "boot_sub": "MOTEUR DE RECONSTRUCTION VOCALE",
    "conn_lost": "Connexion perdue",
    "conn_sub": "Le moteur Lavrentiy n\\'est pas en cours d\\'exécution",
    "sec_tone": "Ton ", "sec_layer": "Couche", "sec_enhance": "Améliorations",
    "sec_mode": "Mode ", "sec_situation": "Situation",
    "tone_casual": "Décontracté", "tone_pro": "Professionnel",
    "tone_friend": "Ami", "tone_formal": "Formel",
    "layer1": "I. Transcrire", "layer1d": "texte brut, sans nettoyage",
    "layer2": "II. Reconstruire", "layer2d": "LLM + ton",
    "layer3": "III. Profil", "layer3d": "+ vocabulaire",
    "layer4": "IV. Dysfluence", "layer4d": "+ dysfluence",
    "lbl_para": "Paralinguistique", "hint_para": "toux/rire",
    "lbl_transcribe": "Transcrire", "hint_transcribe": "insérer [tags] dans le texte",
    "lbl_prosodic": "Prosodique", "hint_prosodic": "ton/énergie/débit",
    "mode_raw": "coller tel quel", "mode_fast": "sans validation", "mode_safe": "+ vérif Falcon",
    "sit_default": "Par défaut", "sit_default_d": "+ usage quotidien",
    "sit_stress": "Stress élevé", "sit_stress_d": "+ assistance totale",
    "sit_reading": "Lecture", "sit_reading_d": "+ quasi fluide",
    "lbl_multitemp": "Multi-Temp", "lbl_prepseed": "Graine Prep",
    "lbl_blocks": "Blocages", "lbl_redos_eng": "Reprises",
    "lbl_nospeech": "Sans Voix", "lbl_logprob": "LogProb Moy.",
    "lbl_sensitive": "◄ sensible", "lbl_tolerant": "tolérant ►",
    "lbl_speech": "PAROLE",
    "lbl_pause": "Ratio Pause", "lbl_wpm_eng": "Mots/Min",
    "lbl_sevmod": "Mod. Sévérité", "lbl_para2": "Paralinguistique",
    "lbl_speaker": "État du locuteur",
    "lbl_base": "base", "lbl_speech2": "parole",
    "sec_shortcuts": "Raccourcis ",
    "hk_record": "Enregistrer", "hk_tone": "Changer Ton",
    "hk_layer": "Changer Couche", "hk_stats": "Stats",
    "hk_quit": "Quitter (×3)",
    "hk_press": "Appuyez sur une touche...",
    "hk_save": "Sauvegarder dans le moteur",
    "sl_words": "Mots", "sl_sessions": "Sessions",
    "sl_wpm": "MPM", "sl_api": "Appels API",
    "sl_difficulty": "Difficulté Moy.", "sl_cost": "Coût Est.",
    "ll_corrections": "Corrections", "ll_fillers": "Tics",
    "ll_vocab": "Vocabulaire", "ll_triggers": "Déclencheurs",
    "ll_editdist": "Dist. Édition", "ll_redos": "Reprises",
    "lp_next": "Prochain cycle", "lp_decay": "Atténuation",
    "tab_console": "Console", "tab_sessions": "Sessions",
    "tab_learning": "Apprentissage", "tab_insights": "Analyses",
    "tab_prep": "Préparer", "tab_calibrate": "Calibrer",
    "tab_tips": "Astuces", "tab_profile": "Profil",
    "console_empty": "En attente d\\'entrée...",
    "learn_empty": "Aucun motif appris pour l\\'instant. Continuez à parler.",
    "learn_report": "📊 RAPPORT HEBDOMADAIRE",
    "insights_empty": "Passez à la Couche 4 pour voir les analyses de bégaiement.",
    "insights_nodata": "Pas encore assez de données. Continuez à utiliser la Couche 4.",
    "sessions_empty": "Commencez à dicter. Les sessions apparaîtront ici.",
    "phoneme_title": "CARTE DE DIFFICULTÉ DES PHONÈMES",
    "covert_title": "MOTIFS D\\'ÉVITEMENT CACHÉS",
    "onset_title": "ANOMALIES D\\'ATTAQUE",
    "onset_sub": "(attaques que vous évitez)",
    "lang_onset_title": "POIDS D\\'ATTAQUE PAR LANGUE",
    "fingerprint_title": "EMPREINTE DE SUBSTITUTION",
    "shadow_title": "DÉRIVE D\\'ÉVITEMENT",
    "lowconf_title": "SEGMENTS DE FAIBLE CONFIANCE",
    "lowconf_sub": "(dernière session — incertitude Whisper près des zones de risque Brown)",
    "fluency_title": "TENDANCE DE FLUIDITÉ",
    "fl_pause": "PAUSE MOY.", "fl_rate": "DÉBIT MOY.",
    "fl_sev": "SÉV+ MOY.", "fl_sessions": "SESSIONS",
    "prep_ph": "Collez votre script, points de discussion ou e-mail ici. Lavrentiy signalera les mots où vous pourriez bégayer et suggérera des alternatives plus sûres.",
    "prep_btn": "PRÉPARER", "prep_scanning": "ANALYSE...",
    "prep_safe": "SÛR", "prep_risky": "RISQUÉ", "prep_trigger": "DÉCLENCHEUR CONNU",
    "prep_seed": "⚡ WHISPER AMORCÉ — le décodeur utilisera ce texte comme contexte",
    "prep_empty": "Tapez ou collez ce que vous allez dire. Appuyez sur PRÉPARER.",
    "prep_nothing": "Rien à préparer.",
    "prep_analyzing": "Analyse du texte et génération d\\'alternatives...",
    "cal_title": "CALIBRATION WHISPER",
    "cal_sub": "Lisez 60 phrases à voix haute. Chaque enregistrement devient un échantillon d\\'entraînement pour la reconnaissance personnalisée.",
    "cal_start": "DÉBUTER CALIBRATION", "cal_resume": "REPRENDRE CALIBRATION",
    "cal_record": "ENREGISTRER", "cal_stop": "ARRÊTER", "cal_saving": "SAUVEGARDE...",
    "cal_skip": "PASSER",
    "cal_instruction": "Lisez cette phrase à voix haute, naturellement. N\\'essayez pas de cacher le bégaiement.",
    "cal_complete": "CALIBRATION TERMINÉE",
    "cal_wer_title": "Résumé WER de calibration",
    "aug_title": "AUGMENTATION DE DONNÉES",
    "aug_sub": "Génère de la parole disfluente synthétique à partir des données de calibration via TTS. Multiplie votre dataset par 5 avec répétitions de mots, répétitions de phrases et insertions d\\'interjections.",
    "aug_btn": "GÉNÉRER DONNÉES AUGMENTÉES",
    "aug_regen": "RÉGÉNÉRER DONNÉES AUGMENTÉES",
    "aug_generating": "GÉNÉRATION...", "aug_starting": "DÉMARRAGE...",
    "wer_title": "TENDANCE WER",
    "wer_sub": "Taux d\\'erreur par mot sur les sessions récentes — moins c\\'est mieux. Montre la qualité de transcription Whisper dans le temps.",
    "wer_avg": "WER MOY.", "wer_recent": "RÉCENT", "wer_samples": "ÉCHANT.",
    "prof_triggers": "Mots déclencheurs", "prof_fillers": "Tics de langage",
    "prof_vocab": "Vocabulaire", "prof_corrections": "Corrections",
    "prof_covert": "Paires d\\'évitement caché",
    "prof_add_trigger": "Ajouter un déclencheur...",
    "prof_add_filler": "Ajouter un tic...",
    "prof_add_vocab": "Ajouter un terme préféré...",
    "prof_heard": "Entendu comme...",
    "prof_should": "Devrait être...",
    "disclaimer": "« Лаврентий fait de son mieux. Vérifiez avant d\\'envoyer. »",
    "prof_new_title": "Nouveau profil",
    "prof_cancel": "Annuler",
    "prof_create": "Créer",
    "prof_name_ph": "Nom",
    "st_idle": "inactif", "st_recording": "enregistre", "st_processing": "traitement", "st_command": "CMD",
    "note_select": "sélectionnez Reconstruire +",
    "help_title": "Guide", "help_sub": "MANUEL D\\'OPÉRATIONS",
    "help_search": "Rechercher...",
    "ha_layers": "Couches", "ha_layers_sub": "L1 Transcrire jusqu\\'à L4 Dysfluence",
    "ha_layers_body": "<strong>L1 Transcrire</strong> — Whisper seul. Voix-vers-texte brut, sans nettoyage IA. Le plus rapide.<br><strong>L2 Reconstruire</strong> — GPT réécrit dans votre ton. Enlève les tics, corrige la grammaire. ~1-2s plus lent.<br><strong>L3 Profil</strong> — Comme L2 + votre vocabulaire et carte de corrections personnels.<br><strong>L4 Dysfluence</strong> — Mode clinique complet. Suivi des dysfluences, score d\\'exposition, réécritures par sévérité.",
    "ha_tone": "Ton", "ha_tone_sub": "Comment GPT réécrit votre parole (L2+)",
    "ha_tone_body": "<strong>Décontracté</strong> — Conversationnel. Contractions, mots simples.<br><strong>Professionnel</strong> — Prêt pour les affaires. Langage propre et précis.<br><strong>Ami</strong> — Relax. Comme un message à un ami.<br><strong>Formel</strong> — Académique/juridique. Sans contractions, précis.",
    "ha_mode": "Mode", "ha_mode_sub": "Étapes du pipeline : RAW, FAST, SAFE",
    "ha_mode_body": "<strong>RAW</strong> <code>coller tel quel</code> — GPT tourne pour les analyses mais colle le texte original Whisper.<br><strong>FAST</strong> <code>sans validation</code> — GPT réécrit, on fait confiance, on colle. Meilleur compromis vitesse/qualité.<br><strong>SAFE</strong> <code>+ vérif Falcon</code> — GPT réécrit, Falcon vérifie la préservation du sens. Plus lent, plus sûr.",
    "ha_enhance": "Améliorations", "ha_enhance_sub": "Analyse paralinguistique + prosodique",
    "ha_enhance_body": "<strong>Paralinguistique</strong> — Détecte toux, rire, soupir, raclement de gorge, respiration, pause. Indépendant de la couche.<br>&nbsp;&nbsp;• <strong>Sous-toggle Transcrire :</strong> ON = tags insérés dans le texte (<code>[Rire]</code>). OFF = uniquement journalisé.<br><br><strong>Prosodique</strong> — Suit le ton (F0), l\\'énergie, le débit. Alimente le modificateur de sévérité au L4.",
    "ha_situation": "Situation", "ha_situation_sub": "Préréglages du moteur en un clic",
    "ha_situation_body": "<strong>Par défaut</strong> — Dictée quotidienne. Sévérité 1.0. Pas d\\'auto-toggles.<br><strong>Stress élevé</strong> — Téléphone, entretien, présentation. Auto-active L4, DAF 100ms, tous les toggles. Sévérité 1.5.<br><strong>Lecture</strong> — Lecture à voix haute. Quasi fluide. Sévérité 0.3, L3 léger.",
    "ha_daf": "DAF", "ha_daf_sub": "Rétroaction Auditive Différée pour la fluidité",
    "ha_daf_body": "Rejoue votre voix dans les écouteurs avec un léger délai. Le délai trompe le cerveau pour qu\\'il ralentisse, améliorant la fluidité. Indépendant de tous les autres réglages.",
    "ha_whisper": "Diagnostic Whisper", "ha_whisper_sub": "Multi-temp, blocages, confiance",
    "ha_whisper_body": "<strong>Multi-Temp</strong> — Lance Whisper à plusieurs températures. Accord = fiable. Désaccord = signalé. 3x plus lent.<br><strong>Blocages</strong> — Blocages de parole détectés (Whisper a halluciné sur du silence).",
    "ha_stats": "Statistiques et barres d\\'apprentissage", "ha_stats_sub": "Cliquable — saute aux onglets de détail",
    "ha_stats_body": "<strong>Mots / Sessions</strong> — Clic → onglet Sessions.<br><strong>Appels API / Coût Est.</strong> — Clic → onglet Console. Coût ~0,0032$/session.<br><strong>Corrections</strong> — Auto-corrections apprises. Clic → onglet Apprentissage.",
    "ha_hotkeys": "Raccourcis", "ha_hotkeys_sub": "Raccourcis clavier (réassignables)",
    "ha_hotkeys_body": "<span class=\"ha-kbd\">F9</span> Démarrer/arrêter enregistrement &nbsp;<span class=\"ha-kbd\">F10</span> Changer tons &nbsp;<span class=\"ha-kbd\">F11</span> Changer couches &nbsp;<span class=\"ha-kbd\">F12</span> Stats &nbsp;<span class=\"ha-kbd\">F3</span> ×3 Quitter",
    "ha_colors": "Couleurs de la console", "ha_colors_sub": "Ce que signifie le texte coloré",
    "ha_colors_body": "<strong style=\"color:#222\">Blanc</strong> — Votre parole transcrite (avec compte de mots)<br><strong style=\"color:#16a34a\">Vert</strong> — Statut pipeline, enregistrement, timing collage<br><strong style=\"color:#a16207\">Jaune</strong> — Analyses parole et diagnostic Whisper<br><strong style=\"color:#dc2626\">Rouge</strong> — Alertes prosodiques<br><strong style=\"color:#92400e\">Marron</strong> — Suspicion de blocage",
    "ha_pipeline": "Comment ça marche", "ha_pipeline_sub": "Ce qui se passe quand vous appuyez sur Enregistrer",
    "ha_pipeline_body": "<strong>1.</strong> Vous parlez, audio capturé.<br><strong>2.</strong> Whisper transcrit avec confiance par mot.<br><strong>3.</strong> Nettoyage rapide (tics, répétitions).<br><strong>4.</strong> Couche choisie traite.<br><strong>5.</strong> Vérif sécurité en SAFE.<br><strong>6.</strong> Colle dans l\\'app ouverte.",
    "ha_tips": "Astuces", "ha_tips_sub": "Trucs pour utilisateurs avancés",
    "ha_tips_body": "• Cliquez sur le <strong>chronomètre</strong> dans l\\'anneau de statut pour le réinitialiser.<br>• <strong>Toggle compact</strong> (en haut à gauche) collapse en barre minimale.<br>• Ton et Mode <strong>auto-collapsent</strong> en L1 (aucun effet).<br>• <strong>Stress élevé</strong> est le bouton panique en un clic : L4 + DAF + tous les toggles.",
}


# Match key:{en:'X',ru:'Y',es:'Z'} where ' inside is escaped as \'.
ENTRY_RE = re.compile(
    r"(\b(\w+):\{en:'((?:\\'|[^'])*)',ru:'((?:\\'|[^'])*)',es:'((?:\\'|[^'])*)')\}"
)


def add_pt_fr(html_text):
    seen_keys = []
    skipped_no_pt = []
    skipped_no_fr = []

    def replacer(match):
        full_prefix = match.group(1)
        key = match.group(2)
        seen_keys.append(key)
        pt = PORTUGUESE.get(key)
        fr = FRENCH.get(key)
        if not pt:
            skipped_no_pt.append(key)
        if not fr:
            skipped_no_fr.append(key)
        if not pt or not fr:
            return match.group(0)  # leave unchanged if either missing
        pt_e = pt.replace("'", "\\'")
        fr_e = fr.replace("'", "\\'")
        return f"{full_prefix},pt:'{pt_e}',fr:'{fr_e}'}}"

    new_text = ENTRY_RE.sub(replacer, html_text)
    return new_text, seen_keys, skipped_no_pt, skipped_no_fr


def main():
    text = HTML.read_text(encoding="utf-8")
    if re.search(r"\{en:'[^']*',ru:'[^']*',es:'[^']*',pt:", text):
        print("Already has pt: entries — skipping (idempotent).")
        return
    new_text, seen, no_pt, no_fr = add_pt_fr(text)
    print(f"Found {len(seen)} I18N entries.")
    print(f"Translated: {len(seen) - len(set(no_pt + no_fr))}")
    if no_pt:
        print(f"Missing PT for {len(no_pt)} keys: {no_pt[:10]}...")
    if no_fr:
        print(f"Missing FR for {len(no_fr)} keys: {no_fr[:10]}...")
    HTML.write_text(new_text, encoding="utf-8")
    print(f"\nWrote {HTML}")


if __name__ == "__main__":
    main()
