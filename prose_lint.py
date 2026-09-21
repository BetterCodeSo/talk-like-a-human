#!/usr/bin/env python3
"""prose_lint: flag machine-sounding prose patterns in French and English.

Usage:
  prose_lint.py FILE [FILE...]      lint files (.md .txt .rst .html .docx ...), exit 1 on errors
  prose_lint.py --strict FILE...    warnings also fail
  prose_lint.py --stdin             lint text read from stdin
  prose_lint.py --hook              Claude Code PostToolUse hook (JSON on stdin), exit 2 on errors
  prose_lint.py --commit-msg FILE   lint a git commit message
  prose_lint.py --git-staged        lint lines added in staged prose files

Suppression: a line containing "ai-style: ignore", or everything between
"ai-style: off" and "ai-style: on" (put them in HTML comments in Markdown).
Env: AI_STYLE_STRICT=1 makes warnings blocking in every mode.
No dependencies beyond the Python 3.8+ standard library.
"""
from __future__ import annotations

import html
import json
import os
import re
import statistics
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path

ERROR, WARN = "error", "warn"
AP = r"['\u2019]"                 # straight or typographic apostrophe
SP = r"[ \u00a0\u202f]*"          # optional (non-breaking) spaces before FR punctuation
LIST = r"(?:[-*+>][ \t]+|\d+[.)][ \t]+)?"  # optional list / quote marker at line start

PROSE_EXT = {".md", ".mdx", ".markdown", ".txt", ".rst", ".adoc", ".asciidoc",
             ".tex", ".html", ".htm", ".docx"}
EXEMPT_NAMES = {"writing-rules.md", "claude-app-instructions.md"}
EXEMPT_DIR = Path.home() / ".config" / "ai-style"

# (rule id, severity, regex, hint). Compiled with IGNORECASE | MULTILINE.
RULES: list[tuple[str, str, str, str]] = [
    # --- punctuation and formatting -------------------------------------------------
    ("TYPO_EM_DASH", ERROR, r"[\u2014\u2015]",
     "em dash: use a comma, parentheses, a colon or two sentences"),
    ("TYPO_EN_DASH_AS_DASH", ERROR, r"(?<=\S)[ \u00a0]\u2013[ \u00a0](?=\S)",
     "en dash used as a sentence dash: restructure"),
    ("TYPO_SPACED_HYPHEN", WARN, r"(?<=[^\s\-|])[ ]-[ ](?=[^\s\-|])",
     "spaced hyphen used as a dash: restructure"),
    ("TYPO_EMOJI_MARKER", ERROR,
     r"^[ \t]*(?:[-*+][ \t]+|\d+[.)][ \t]+|#{1,6}[ \t]+)?"
     r"[\u2705\u274c\u274e\u2714\u2716\u2728\u26a1\u26a0\u2b50\u27a1\U0001F300-\U0001FAFF]",
     "emoji used as bullet, status or heading marker"),
    ("TYPO_EMOJI", WARN, r"[\u2705\u2728\u2b50\U0001F300-\U0001FAFF]",
     "emoji in prose"),
    ("TYPO_ARROW_PROSE", WARN, r"(?<=\w)[ ]?(?:\u2192|\u21d2|->|=>)[ ]?(?=\w)",
     "arrow standing in for a verb: write the verb"),
    ("FMT_BOLD_LABEL_BULLET", ERROR,
     r"^[ \t]*(?:[-*+]|\d+[.)])[ \t]+\*\*[^*\n]{1,80}?\*\*" + SP + r":"
     r"|^[ \t]*(?:[-*+]|\d+[.)])[ \t]+\*\*[^*\n]{1,80}?:\*\*",
     "'**Label:** text' bullet: write a plain sentence or use a real table"),
    ("FMT_SUMMARY_HEADING", WARN,
     r"^#{1,6}[ \t]*(?:key takeaways?|takeaways?|tl;?dr|in summary|summary|en r[ée]sum[ée]"
     r"|points? cl[ée]s?|[àa] retenir|ce qu" + AP + r"il faut retenir|r[ée]capitulatif|en bref|conclusion)\b",
     "summary section: keep only if it adds information not stated above"),

    # --- sentence templates -------------------------------------------------------------
    ("RHET_NOT_X_ITS_Y", ERROR,
     r"\b(?:it|this|that|these|they)(?:" + AP + r"s| is| are|" + AP + r"re) not "
     r"(?:just |only |merely |simply |really )?(?:about )?[^.;:!?\n]{1,80}?[,;.]\s*"
     r"(?:it|this|that|they)(?:" + AP + r"s| is| are|" + AP + r"re)\b",
     "contrastive reframe 'it's not X, it's Y': state Y directly"),
    ("RHET_ISNT_ABOUT", ERROR,
     r"\b(?:isn" + AP + r"t|is not|aren" + AP + r"t|are not|wasn" + AP + r"t|was not) "
     r"(?:just |only |really |merely )?about\b[^.!?\n]{0,80}[.;,]\s*"
     r"(?:it|this|they)(?:" + AP + r"s| is| are|" + AP + r"re| was) (?:about|what)\b",
     "contrastive reframe 'isn't about X, it's about Y'"),
    ("RHET_NOT_ONLY_EN", ERROR, r"\bnot only\b[^.!?\n]{1,120}?\bbut (?:also|too)\b",
     "'not only... but also' emphasis"),
    ("RHET_NOT_BUT_EN", WARN,
     r"\bnot (?:just |only |merely |simply )?(?:a |an |the )?[\w-]+(?: [\w-]+){0,4}, but (?:a |an |the |rather )?",
     "'not X, but Y' construction: consider stating Y directly"),
    ("RHET_TRAILING_NOT", WARN, r"[,;] not (?:a |an |the )?[\w-]+(?: [\w-]+){0,3}[.!]",
     "tacked-on correction ', not Y.'"),
    ("RHET_CE_NEST_PAS_FR", ERROR,
     r"\b(?:ce|cela|[çc]a)\s+n" + AP + r"(?:est|[ée]tait)\s+pas\s+"
     r"(?:seulement\s+|juste\s+|simplement\s+|uniquement\s+)?[^.!?;\n]{1,80}?[,;.]\s*"
     r"(?:c" + AP + r"(?:est|[ée]tait)(?!\s+pourquoi|-[àa]-dire)|mais|il\s+s" + AP + r"agit)\b",
     "recadrage « ce n'est pas X, c'est Y » : énoncer Y directement"),
    ("RHET_IL_NE_SAGIT_PAS_FR", ERROR,
     r"\bil\s+ne\s+s" + AP + r"agit\s+(?:pas|plus)\s+(?:seulement\s+|simplement\s+|juste\s+|uniquement\s+)?"
     r"(?:de|d" + AP + r"|du|des)\b[^.!?\n]{1,100}?(?:\bmais\b|\bil\s+s" + AP + r"agit\b)",
     "recadrage « il ne s'agit pas de X, mais de Y »"),
    ("RHET_NON_SEULEMENT_FR", ERROR,
     r"\bnon\s+seulement\b[^.!?\n]{1,120}?\bmais\s+(?:aussi|[ée]galement|encore|surtout)\b",
     "« non seulement... mais aussi » emphatique"),
    ("RHET_PAS_X_MAIS_FR", WARN, r"(?:^|[.!?]\s+)pas\s+[^.!?\n]{1,40},\s+mais\b",
     "« Pas X, mais Y » en début de phrase"),
    ("RHET_Q_REVEAL_EN", ERROR,
     r"(?:^|[.!?:]\s+)(?:the\s+)?(?:result|catch|kicker|problem|fix|answer|reason|takeaway|upshot|verdict"
     r"|twist|trick|secret|difference|outcome|payoff|bottom line|why|how|so what)\s*\?[ \t]+\S",
     "self-answered question: make the statement"),
    ("RHET_Q_REVEAL_FR", ERROR,
     r"(?:^|[.!?:]\s+)(?:le\s+|la\s+|l" + AP + r")?(?:r[ée]sultat|hic|probl[èe]me|souci|solution|r[ée]ponse"
     r"|raison|secret|astuce|diff[ée]rence|verdict|cons[ée]quence|pi[èe]ge|bilan|pourquoi|comment)"
     + SP + r"\?[ \t]+\S",
     "question rhétorique suivie de sa réponse : affirmer directement"),
    ("RHET_Q_BECAUSE", ERROR, r"\?[ \t]+(?:parce\s+qu|because\b|simple" + SP + r":)",
     "question answered by 'because' / « parce que »"),
    ("RHET_COLON_REVEAL_EN", ERROR,
     r"\bhere(?:" + AP + r"s| is) (?:the thing|why|what|how|the kicker|the catch|the deal|the problem|the trick|the twist)\b"
     r"|\b(?:the kicker|the catch|the twist|plot twist|spoiler|the upshot|the good news|the bad news"
     r"|the short answer|the honest answer|the real answer|the punchline|bottom line)[ \t]*[:?]",
     "setup-and-reveal: make the statement"),
    ("RHET_COLON_REVEAL_FR", ERROR,
     r"\b(?:bonne|mauvaise)\s+nouvelle" + SP + r":"
     r"|\b(?:le\s+hic|le\s+pi[èe]ge|spoiler|la\s+r[ée]ponse\s+courte|en\s+deux\s+mots)" + SP + r":"
     r"|\bvoici\s+(?:le\s+truc|pourquoi|le\s+hic|le\s+probl[èe]me|l" + AP + r"astuce)\b",
     "effet d'annonce « Le hic : », « Bonne nouvelle : », « Voici pourquoi »"),
    ("RHET_COLON_OPENER_FR", WARN,
     r"(?:^|[.!?]\s+)(?:r[ée]sultat|concr[èe]tement|en\s+clair|autrement\s+dit|bref|traduction"
     r"|le\s+constat|la\s+cons[ée]quence)" + SP + r":",
     "ouverture « Résultat : » / « Concrètement : »"),
    ("RHET_REAL_X", ERROR,
     r"\bthe real (?:question|issue|problem|answer|story|challenge|win|risk|lesson|work)\b"
     r"|\bla\s+vraie\s+(?:question|difficult[ée]|r[ée]ponse|le[çc]on)\b"
     r"|\ble\s+vrai\s+(?:probl[èe]me|enjeu|sujet|d[ée]fi|risque|gain)\b",
     "'the real X' / « le vrai X »"),
    ("RHET_LESS_MORE", ERROR,
     r"\b(?:less|fewer)\s+[\w-]+,\s+more\s+[\w-]+"
     r"|\bmoins\s+(?:de\s+|d" + AP + r")[\w-]+,\s+plus\s+(?:de\s+|d" + AP + r")[\w-]+",
     "aphoristic 'less X, more Y'"),
    ("RHET_WHETHER", ERROR,
     r"\bwhether you(?:" + AP + r"re| are)\b|\bque\s+vous\s+soyez\b|\bque\s+tu\s+sois\b",
     "'whether you're X or Y' / « que vous soyez X ou Y »"),
    ("RHET_COMES_IN", ERROR,
     r"\bthat" + AP + r"s where\b[^.\n]{1,50}?\bcomes? in\b"
     r"|\bc" + AP + r"est\s+l[àa]\s+qu" + AP + r"?[^.\n]{0,50}?\b(?:entre|entrent)\s+en\s+(?:jeu|sc[èe]ne)\b"
     r"|\bc" + AP + r"est\s+l[àa]\s+que\s+tout\s+(?:change|se\s+joue)\b",
     "'that's where X comes in' / « c'est là que X entre en jeu »"),
    ("RHET_SIGNPOST", ERROR,
     r"\blet" + AP + r"s (?:dive|delve|break (?:it|this|that) down|unpack|explore|take a (?:closer |quick )?look"
     r"|walk through|get (?:into|started)|zoom (?:in|out))\b"
     r"|\b(?:plongeons|d[ée]cortiquons|explorons|entrons\s+dans\s+le\s+vif|voyons\s+(?:ensemble|de\s+plus\s+pr[èe]s)"
     r"|passons\s+en\s+revue|faisons\s+le\s+point)\b",
     "signposting: just start"),
    ("RHET_LIST_ANNOUNCE", WARN,
     r"\b(?:here are|below are|voici|ci-dessous)\s+(?:the\s+|les\s+|des\s+)?"
     r"(?:\d+\s+|three\s+|four\s+|five\s+|trois\s+|quatre\s+|cinq\s+)?"
     r"(?:key\s+|main\s+|essential\s+|major\s+|principaux\s+|principales\s+|grands\s+|grandes\s+)?"
     r"(?:points|takeaways|steps|reasons|things|[ée]tapes|raisons|[ée]l[ée]ments|axes|piliers|leviers)\b[^:\n]{0,40}" + SP + r":",
     "announced list: let the list or the heading speak"),

    # --- openers, closers, meta-talk ------------------------------------------------------
    ("META_PRAISE", ERROR,
     r"\b(?:great|excellent|good|fantastic|interesting) question\b"
     r"|(?:^|[.!?]\s+)(?:absolutely|certainly|of course)[!,.]"
     r"|\byou" + AP + r"re (?:absolutely |completely |totally )?right\b"
     r"|\b(?:excellente|bonne)\s+question\b"
     r"|(?:^|[.!?]\s+)(?:absolument|tout\s+[àa]\s+fait|bien\s+s[ûu]r|certainement)" + SP + r"!"
     r"|\b(?:vous\s+avez|tu\s+as)\s+(?:enti[èe]rement\s+|tout\s+[àa]\s+fait\s+|parfaitement\s+)?raison\b",
     "praise or agreement opener"),
    ("META_OFFER", ERROR,
     r"\bI hope (?:this|that|it) helps\b|\blet me know if\b|\bfeel free to\b"
     r"|\bhappy to (?:help|assist|dig|expand)\b|\bwould you like me to\b|\bwant me to\b|\bshall I\b"
     r"|\bj" + AP + r"esp[èe]re\s+que\s+(?:cela|[çc]a|ceci)\s+(?:vous|t" + AP + r"|te)\b"
     r"|\b(?:souhaitez-vous|voulez-vous|veux-tu|souhaites-tu)\s+que\s+je\b"
     r"|\bsi\s+(?:vous\s+le\s+souhaitez|tu\s+veux),\s+je\s+peux\b",
     "closing offer or pleasantry"),
    ("META_OFFER_SOFT", WARN, r"\bdon" + AP + r"t hesitate to\b|\bn" + AP + r"h[ée]sit(?:ez|e)\s+pas\b",
     "« n'hésitez pas » / 'don't hesitate'"),
    ("META_RECAP", ERROR,
     r"(?:^|[.!?]\s+)" + LIST + r"(?:in summary|in conclusion|in short|to sum up|to summarize|all in all"
     r"|at the end of the day|the bottom line is|in a nutshell|en\s+r[ée]sum[ée]|en\s+somme|en\s+d[ée]finitive"
     r"|au\s+final|pour\s+r[ée]sumer|pour\s+conclure|en\s+bref|en\s+un\s+mot)\b",
     "recap ending: stop when the content stops"),
    ("META_RECAP_SOFT", WARN,
     r"(?:^|[.!?]\s+)" + LIST + r"(?:ultimately|overall|en\s+conclusion|finalement|globalement)\s*,",
     "recap connector"),
    ("META_NARRATION", ERROR,
     r"\bhere(?:" + AP + r"s| is) (?:a|an|the|your) (?:comprehensive|detailed|complete|revised|updated|improved"
     r"|polished|quick|brief|concise|full|thorough|structured|high-level)\b"
     r"|\bvoici\s+(?:une?|la|le|les|votre|ta|ton)\s+(?:version|synth[èe]se|r[ée]capitulatif|aper[çc]u"
     r"|vue\s+d" + AP + r"ensemble|analyse|proposition|r[ée]ponse)\s+(?:r[ée]vis[ée]e?|am[ée]lior[ée]e?"
     r"|mise\s+[àa]\s+jour|corrig[ée]e?|compl[èe]te|d[ée]taill[ée]e?|structur[ée]e?|claire|concise|synth[ée]tique)\b"
     r"|\bas an AI\b|\ben\s+tant\s+qu" + AP + r"IA\b",
     "narrating the output"),
    ("META_EMPATHY", ERROR,
     r"\bI (?:completely |totally |fully )?understand (?:your|the) (?:frustration|concern|confusion)\b"
     r"|\bje\s+comprends\s+(?:tout\s+[àa]\s+fait\s+|parfaitement\s+|bien\s+)?(?:votre|ta)\s+"
     r"(?:frustration|inqui[ée]tude|pr[ée]occupation|confusion)\b",
     "empathy formula"),

    # --- vocabulary: unambiguous tells -----------------------------------------------------
    ("VOCAB_EN", ERROR,
     r"\bdelv(?:e|es|ed|ing)\b|\btapestr(?:y|ies)\b|\btestament to\b|\bgame[- ]?changer\b|\bever[- ]evolving\b"
     r"|\bfast[- ]paced (?:world|landscape|environment)\b"
     r"|\bin today" + AP + r"s (?:digital |modern |fast[- ]paced |rapidly (?:changing|evolving) )?(?:world|landscape|age|era|environment)\b"
     r"|\bnavigat(?:e|ing) the (?:complexities|landscape|world|intricacies|nuances)\b"
     r"|\bunlock(?:s|ing)? (?:the )?(?:full )?potential\b|\bharness(?:es|ing)? the (?:full )?power\b"
     r"|\b(?:it" + AP + r"s|it is) worth (?:noting|mentioning|highlighting|flagging)\b|\bworth (?:noting|flagging) (?:that|here)\b"
     r"|\bplays? an? (?:crucial|pivotal|vital|key|critical|central) role\b|\bin the realm of\b|\bembark(?:s|ing)? on\b"
     r"|\ba symphony of\b|\bserves? as a (?:reminder|testament)\b|\bunderscor(?:e|es|ing) the importance\b"
     r"|\bthe honest (?:answer|take|truth)\b|\bto be (?:honest|clear|fair),",
     "stock LLM phrasing: use the plain, specific word"),
    ("VOCAB_FR", ERROR,
     r"\bdans\s+un\s+monde\s+(?:en\s+(?:constante|perp[ée]tuelle|pleine)\s+(?:[ée]volution|mutation|transformation)|o[ùu])\b"
     r"|\b[àa]\s+l" + AP + r"[èe]re\s+(?:du\s+num[ée]rique|de\s+l" + AP + r"IA|digitale)\b"
     r"|\bforce\s+est\s+de\s+constater\b"
     r"|\bil\s+est\s+(?:important|essentiel|crucial|primordial|int[ée]ressant)\s+de\s+(?:noter|souligner|rappeler|mentionner|garder\s+[àa]\s+l" + AP + r"esprit)\b"
     r"|\bil\s+convient\s+de\s+(?:noter|souligner|rappeler|mentionner)\b|\bn" + AP + r"est\s+plus\s+[àa]\s+d[ée]montrer\b"
     r"|\bjoue(?:nt)?\s+un\s+r[ôo]le\s+(?:cl[ée]|crucial|essentiel|central|majeur|d[ée]terminant|primordial)\b"
     r"|\btirer\s+pleinement\s+parti\b|\bexploiter\s+(?:tout\s+le|pleinement\s+le)\s+potentiel\b|\blib[ée]rer\s+(?:tout\s+)?le\s+potentiel\b"
     r"|\bun\s+(?:v[ée]ritable|vrai)\s+(?:game[- ]?changer|atout|levier|tournant|pilier|catalyseur)\b"
     r"|\bs" + AP + r"inscri(?:t|vent)\s+dans\s+une\s+(?:d[ée]marche|logique|dynamique)\b"
     r"|\bnaviguer\s+(?:dans|[àa]\s+travers)\s+(?:la\s+complexit[ée]|les\s+m[ée]andres|le\s+paysage)\b"
     r"|\ble\s+paysage\s+(?:actuel|technologique|num[ée]rique|de\s+l" + AP + r"IA)\b"
     r"|\bplong(?:er|eons|ez)\s+(?:dans|au\s+c(?:œ|oe)ur)\b|\ben\s+constante\s+[ée]volution\b"
     r"|\bau\s+c(?:œ|oe)ur\s+(?:de\s+la|de\s+l" + AP + r"|des|du|de\s+votre|de\s+notre)\s*(?:strat[ée]gie|d[ée]marche|transformation|r[ée]flexion|projet|dispositif)\b",
     "tournure stéréotypée : mot simple et précis, ou suppression"),
    ("CALQUE_FR", ERROR,
     r"\badress(?:er|ons|ez|[ée]|[ée]e|[ée]s|[ée]es|e|ent)\s+(?:un|le|ce|les|des|ces|cette|la|l" + AP + r")\s*"
     r"(?:probl[èe]mes?|sujets?|enjeux|besoins?|questions?|risques?|d[ée]fis?)\b"
     r"|\bfai(?:t|re|sait)\s+(?:du|beaucoup\s+de)\s+sens\b|\bimpactante?s?\b|\bd[ée]livrer\s+(?:de\s+la\s+)?valeur\b",
     "calque de l'anglais"),
    ("HEDGE_STACK", ERROR,
     r"\b(?:could|may|might|can)\s+potentially\b"
     r"|\b(?:peut|pourrait|pourraient|peuvent|pourra)\s+(?:potentiellement|[ée]ventuellement)\b",
     "stacked hedge: pick one or commit"),

    # --- vocabulary: context-dependent ----------------------------------------------------
    ("VOCAB_EN_SOFT", WARN,
     r"\b(?:leverag(?:e|es|ed|ing)|robust(?:ness)?|seamless(?:ly)?|crucial(?:ly)?|pivotal|comprehensive|holistic"
     r"|nuanced|multifaceted|intricate|underscor(?:e|es|ed|ing)|showcas(?:e|es|ed|ing)|paramount|foster(?:s|ed|ing)?"
     r"|streamlin(?:e|es|ed|ing)|empower(?:s|ed|ing)?|elevat(?:e|es|ed|ing)|cutting[- ]edge|genuinely|truly"
     r"|incredibly|notably|importantly|landscape|realm|navigat(?:e|es|ing)|harness(?:es|ed|ing)?|unlock(?:s|ed|ing)?"
     r"|straightforward|load[- ]bearing|quietly|honestly|arguably)\b",
     "overused word: keep only if it is the precise term"),
    ("VOCAB_FR_SOFT", WARN,
     r"\b(?:crucia(?:le|ux|les)|primordia(?:l|le|ux|les)|incontournables?|robustes?|robustesse|fluidifi\w*"
     r"|holistiques?|v[ée]ritables?|v[ée]ritablement|levi(?:er|ers)|[ée]cosyst[èe]mes?|atouts?\s+majeurs?|enjeux?\s+majeurs?"
     r"|tir(?:er|ez|ons|e)\s+parti|vraiment|r[ée]ellement|particuli[èe]rement|extr[êe]mement|incroyablement"
     r"|synergies?|il\s+semblerait\s+que)\b",
     "mot surutilisé : garder seulement si c'est le terme exact"),
    ("VOCAB_FR_CLE_ADJ", WARN,
     r"\b(?:enjeu|facteur|[ée]l[ée]ment|point|[ée]tape|acteur|chiffre|indicateur|moment|r[ôo]le|aspect|levier|atout"
     r"|comp[ée]tence|message|id[ée]e|question|information|notion)s?\s+cl[ée]s?\b",
     "« clé » adjectif : préciser en quoi c'est important"),
    ("OPENER_CONNECTOR", WARN,
     r"^[ \t]*" + LIST + r"(?:moreover|furthermore|additionally|that said|importantly|notably|crucially|interestingly"
     r"|en\s+effet|par\s+ailleurs|de\s+plus|en\s+outre|ainsi|d[èe]s\s+lors|de\s+fait|concr[èe]tement|globalement"
     r"|d" + AP + r"ailleurs)\s*,",
     "reflexive paragraph opener"),
    ("VAGUE_AUTHORITY", WARN,
     r"\b(?:experts|studies|research)\s+(?:agree|show|suggest|say|believe)s?\b"
     r"|\bles\s+experts\s+(?:s" + AP + r"accordent|estiment|recommandent)\b|\bde\s+nombreuses\s+[ée]tudes\b"
     r"|\bselon\s+(?:certains|de\s+nombreux|les)\s+experts\b",
     "unsourced authority: name the source or drop it"),
    ("PERSONIFICATION", WARN,
     r"\b(?:data|numbers|results|code|figures)\s+(?:tells?|speaks?)\s+(?:a\s+story|for\s+(?:itself|themselves))\b"
     r"|\bles\s+(?:chiffres|donn[ée]es|r[ée]sultats)\s+(?:parlent\s+d" + AP + r"eux-m[êe]mes|racontent)\b",
     "personified abstraction"),
]

COMPILED = [(rid, sev, re.compile(rx, re.IGNORECASE | re.MULTILINE), hint) for rid, sev, rx, hint in RULES]

# Case-sensitive: three or more capitalised fragments of 1 to 3 words in a row ("Simple. Rapide. Efficace.")
STACCATO = re.compile(
    r"(?:^|(?<=[.!?] ))(?:[A-ZÀ-Ý][\w'\u2019-]*(?: [\w'\u2019-]+){0,2}[.!] +){2,}"
    r"[A-ZÀ-Ý][\w'\u2019-]*(?: [\w'\u2019-]+){0,2}[.!]", re.MULTILINE)
BOLD = re.compile(r"\*\*[^*\n]+\*\*")
STRUCT_LINE = re.compile(r"^[ \t]*(?:[-*+>|]|\d+[.)]|#{1,6}\s)")
TRIAD = re.compile(r"\b[\w'\u2019-]+, [\w'\u2019-]+,? (?:and|or|et|ou) [\w'\u2019-]+\b")


@dataclass
class Finding:
    line: int
    col: int
    sev: str
    rule: str
    excerpt: str
    hint: str


# ---------------------------------------------------------------- text extraction ----
def _blank(m: re.Match) -> str:
    return re.sub(r"[^\n]", " ", m.group(0))


def suppress(text: str) -> str:
    lines, off = text.split("\n"), False
    for i, line in enumerate(lines):
        if "ai-style: off" in line:
            off, lines[i] = True, ""
        elif "ai-style: on" in line:
            off, lines[i] = False, ""
        elif off or "ai-style: ignore" in line:
            lines[i] = ""
    return "\n".join(lines)


def mask_markdown(text: str) -> str:
    out, fence = [], None
    for line in text.split("\n"):
        m = re.match(r"^\s*(`{3,}|~{3,})", line)
        if m:
            marker = m.group(1)[:3]
            fence = marker if fence is None else (None if marker == fence else fence)
            out.append("")
            continue
        if fence:
            out.append("")
            continue
        line = re.sub(r"`[^`\n]*`", _blank, line)
        line = re.sub(r"https?://\S+", _blank, line)
        line = re.sub(r"<!--.*?-->", _blank, line)
        out.append(line)
    return "\n".join(out)


def html_to_text(text: str) -> str:
    text = re.sub(r"<(script|style|pre|code)\b.*?</\1>", _blank, text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", _blank, text)
    return html.unescape(text)


def docx_to_text(path: Path) -> str:
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8", "replace")
    paras = re.findall(r"<w:p(?:\s[^>]*)?>.*?</w:p>", xml, flags=re.S)
    return "\n".join(
        html.unescape("".join(re.findall(r"<w:t(?:\s[^>]*)?>(.*?)</w:t>", p, flags=re.S))) for p in paras)


def kind_of(path: str) -> str:
    ext = Path(path).suffix.lower()
    if ext in {".md", ".mdx", ".markdown"}:
        return "md"
    if ext in {".html", ".htm"}:
        return "html"
    return "text"


def prepare(text: str, kind: str) -> str:
    text = suppress(text)
    if kind == "md":
        text = mask_markdown(text)
    elif kind == "html":
        text = html_to_text(text)
    return text


# ---------------------------------------------------------------------- linting ----
def _pos(text: str, idx: int) -> tuple[int, int]:
    line = text.count("\n", 0, idx) + 1
    return line, idx - (text.rfind("\n", 0, idx) + 1) + 1


def _excerpt(text: str, start: int, end: int) -> str:
    s = max(text.rfind("\n", 0, start) + 1, start - 40)
    e = min([i for i in (text.find("\n", end), end + 40) if i != -1] or [end + 40])
    return " ".join(text[s:e].split())


def lint_text(raw: str, kind: str = "text", doc_checks: bool = True) -> list[Finding]:
    text = prepare(raw, kind)
    found: dict[tuple[int, int], Finding] = {}

    def add(idx_start: int, idx_end: int, sev: str, rule: str, hint: str) -> None:
        lead = re.match(r"[.!?:]?\s*", text[idx_start:idx_end])
        if lead and lead.end() < idx_end - idx_start:
            idx_start += lead.end()
        line, col = _pos(text, idx_start)
        key = (line, col)
        if key in found and found[key].sev == ERROR:
            return
        found[key] = Finding(line, col, sev, rule, _excerpt(text, idx_start, idx_end), hint)

    for rid, sev, rx, hint in COMPILED:
        for m in rx.finditer(text):
            add(m.start(), m.end(), sev, rid, hint)
    for m in STACCATO.finditer(text):
        add(m.start(), m.end(), ERROR, "RHET_STACCATO", "run of short fragments for effect: write a sentence")

    offset = 0
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped and not STRUCT_LINE.match(line) and BOLD.search(line):
            m = BOLD.search(line)
            add(offset + m.start(), offset + m.end(), WARN, "FMT_BOLD_IN_PROSE", "bold inside running prose")
        h = re.match(r"^#{1,6}\s+(.*)", line)
        if h:
            words = [w for w in re.findall(r"[^\W\d_][\w'\u2019-]*", h.group(1)) if len(w) >= 4 and not w.isupper()]
            if len(words) >= 3 and all(w[0].isupper() for w in words):
                add(offset, offset + len(line), WARN, "FMT_TITLE_CASE", "Title Case heading: use sentence case")
        offset += len(line) + 1

    if doc_checks:
        prose = "\n".join(l for l in text.split("\n") if l.strip() and not re.match(r"^\s*(?:#|\|)", l))
        words = prose.split()
        sentences = [s for s in re.split(r"(?<=[.!?])\s+", prose) if len(s.split()) >= 3]
        if len(sentences) >= 15:
            lengths = [len(s.split()) for s in sentences]
            cv = statistics.pstdev(lengths) / statistics.mean(lengths)
            if cv < 0.35:
                found[(0, 1)] = Finding(0, 1, WARN, "RHYTHM_UNIFORM", f"sentence-length CV={cv:.2f}",
                                        "uniform sentence length: vary the rhythm")
        if len(words) >= 150:
            density = len(TRIAD.findall(prose)) * 1000 / len(words)
            if density > 6:
                found[(0, 2)] = Finding(0, 2, WARN, "RHYTHM_TRIADS", f"{density:.1f} triads per 1000 words",
                                        "reflexive groups of three")
    return sorted(found.values(), key=lambda f: (f.line, f.col))


def lint_path(path: Path) -> list[Finding]:
    if path.suffix.lower() == ".docx":
        return lint_text(docx_to_text(path), "text")
    return lint_text(path.read_text(encoding="utf-8", errors="replace"), kind_of(str(path)))


# ------------------------------------------------------------------------ output ----
def fmt(label: str, f: Finding) -> str:
    loc = f"{label}:{f.line}:{f.col}" if f.line else label
    return f"{loc}: {f.sev} {f.rule}: \"{f.excerpt}\" -> {f.hint}"


def is_exempt(path: str) -> bool:
    p = Path(path).expanduser()
    try:
        p.resolve().relative_to(EXEMPT_DIR.resolve())
        return True
    except ValueError:
        return p.name in EXEMPT_NAMES


def strict() -> bool:
    return os.environ.get("AI_STYLE_STRICT") == "1"


# ------------------------------------------------------------------------- modes ----
def mode_hook() -> int:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    ti = data.get("tool_input") or {}
    path = ti.get("file_path") or ""
    if not path or Path(path).suffix.lower() not in PROSE_EXT or is_exempt(path):
        return 0
    if "content" in ti:
        text, doc = ti["content"], True
    elif "new_string" in ti:
        text, doc = ti["new_string"], False
    elif "edits" in ti:
        text, doc = "\n".join(e.get("new_string", "") for e in ti["edits"]), False
    elif Path(path).exists():
        return report_hook(path, lint_path(Path(path)))
    else:
        return 0
    return report_hook(path, lint_text(text, kind_of(path), doc_checks=doc))


def report_hook(path: str, findings: list[Finding]) -> int:
    errors = [f for f in findings if f.sev == ERROR]
    if not (findings if strict() else errors):
        return 0
    print(f"prose_lint: machine-sounding patterns in the text just written to {path} "
          "(line numbers are relative to the written text).", file=sys.stderr)
    for f in findings[:40]:
        print("  " + fmt("L", f), file=sys.stderr)
    if len(findings) > 40:
        print(f"  ... {len(findings) - 40} more", file=sys.stderr)
    print("Rewrite the flagged sentences with a different structure (not a synonym swap) and save again. "
          "Warnings: keep the word only if it is the precise technical term. "
          "Rules: ~/.config/ai-style/writing-rules.md", file=sys.stderr)
    return 2


def mode_files(paths: list[str], use_strict: bool) -> int:
    failed = False
    for p in paths:
        path = Path(p)
        if not path.is_file():
            print(f"{p}: not a file", file=sys.stderr)
            continue
        findings = lint_path(path)
        for f in findings:
            print(fmt(p, f))
        failed |= any(f.sev == ERROR or use_strict for f in findings)
    return 1 if failed else 0


def mode_commit_msg(path: str) -> int:
    lines = Path(path).read_text(encoding="utf-8", errors="replace").split("\n")
    msg = "\n".join(l for l in lines if not l.startswith("#")).split("\n------------------------ >8")[0]
    findings = lint_text(msg, "text", doc_checks=False)
    for f in findings:
        print(fmt("commit-msg", f), file=sys.stderr)
    return 1 if any(f.sev == ERROR or strict() for f in findings) else 0


def mode_git_staged() -> int:
    names = subprocess.run(["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
                           capture_output=True, text=True).stdout.split()
    failed = False
    for name in names:
        if Path(name).suffix.lower() not in PROSE_EXT - {".docx"} or is_exempt(name):
            continue
        diff = subprocess.run(["git", "diff", "--cached", "-U0", "--", name],
                              capture_output=True, text=True).stdout
        added = "\n".join(l[1:] for l in diff.split("\n") if l.startswith("+") and not l.startswith("+++"))
        findings = lint_text(added, kind_of(name), doc_checks=False)
        for f in findings:
            print(fmt(f"{name} (added lines)", f), file=sys.stderr)
        failed |= any(f.sev == ERROR or strict() for f in findings)
    return 1 if failed else 0


def main(argv: list[str]) -> int:
    if not argv or argv[0] in {"-h", "--help"}:
        print(__doc__)
        return 0
    if argv[0] == "--hook":
        return mode_hook()
    if argv[0] == "--stdin":
        findings = lint_text(sys.stdin.read(), "md")
        for f in findings:
            print(fmt("stdin", f))
        return 1 if any(f.sev == ERROR or strict() for f in findings) else 0
    if argv[0] == "--commit-msg":
        return mode_commit_msg(argv[1])
    if argv[0] == "--git-staged":
        return mode_git_staged()
    use_strict = strict()
    if argv[0] == "--strict":
        use_strict, argv = True, argv[1:]
    return mode_files(argv, use_strict)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
