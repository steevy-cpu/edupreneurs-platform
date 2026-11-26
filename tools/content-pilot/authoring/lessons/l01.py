from ..lib import CO, EX, C, ExampleCheck, H, Lesson, P, Q

S1 = "p. imprimée 38 (PDF p. 39), unité « Nombres et calculs », 7e année"
LESSON = Lesson(
    slug="lire-ecrire-comparer-entiers",
    position=1,
    titles={"fr": "Lire, écrire et comparer des nombres entiers", "ht": "Li, ekri ak konpare nonb antye"},
    objectives={
        "fr": [
            "Lire et écrire un nombre entier naturel jusqu'à 999 999.",
            "Dire la valeur de chaque chiffre selon sa place.",
            "Comparer et ranger des nombres entiers avec les signes <, > et =.",
        ],
        "ht": [
            "Li ak ekri yon nonb antye natirèl jouk 999 999.",
            "Di ki valè chak chif genyen dapre plas li.",
            "Konpare ak ranje nonb antye ak siy yo <, > ak =.",
        ],
    },
    refs=[
        {
            "source": "S1",
            "locator": f"{S1} : « Lire, écrire et représenter les nombres entiers naturels » ; « Classer (situer, ordonner, comparer) les nombres entiers naturels »",
            "relation": "partial",
            "note": "Entiers naturels seulement : fractions et décimaux de ces mêmes items ne sont pas traités ici. Pas de demi-droite graduée (le format v1 n'a pas d'image).",
        },
        {
            "source": "S2",
            "locator": "PDF p. 9 (janvier, semaine 3), Algèbre 2.6.1 « Comparer et ordonner des entiers naturels »",
            "relation": "direct",
            "note": "Programme à compétences minimales 2019-2020 : mesure temporaire, ne remplace pas les programmes de 1989.",
        },
    ],
    blocks={
        "fr": [
            P(
                "objectifs",
                "À la fin de cette leçon, tu sauras lire et écrire un nombre entier jusqu'à 999 999, dire ce que vaut chaque chiffre, et comparer deux nombres.",
            ),
            P(
                "intro",
                "Un stade peut accueillir 2 450 personnes. Un autre stade en accueille 1 980. Lequel est le plus grand ? Pour répondre, il faut savoir lire et comparer des nombres.",
            ),
            H("valeur-titre", "Chaque chiffre a une valeur selon sa place"),
            P(
                "valeur",
                "Dans un nombre, un chiffre vaut plus ou moins selon sa place. De la droite vers la gauche, on trouve les unités, les dizaines, les centaines, puis les milliers. Dans 4 305, le chiffre 4 est à la place des milliers : il vaut 4 000. Le chiffre 3 vaut 300. Le chiffre 0 montre qu'il n'y a aucune dizaine.",
            ),
            EX(
                "exemple-decomposition",
                "Décomposer 4 305",
                ["4 305 = 4 000 + 300 + 0 + 5", "4 milliers, 3 centaines, 0 dizaine et 5 unités", "On lit : quatre mille trois cent cinq"],
            ),
            P(
                "lire",
                "Pour lire un grand nombre, on le coupe en tranches de trois chiffres en partant de la droite. 12 480 se lit « douze mille quatre cent quatre-vingts ».",
            ),
            H("comparer-titre", "Comparer deux nombres"),
            P(
                "comparer",
                "Pour comparer deux nombres, on compte d'abord leurs chiffres : celui qui a le plus de chiffres est le plus grand. S'ils ont autant de chiffres, on compare les chiffres de gauche à droite et on s'arrête au premier chiffre qui n'est pas le même.",
            ),
            EX(
                "exemple-comparer-1",
                "Comparer 2 450 et 1 980",
                ["Les deux nombres ont 4 chiffres.", "On compare les milliers : 2 et 1.", "2 est plus grand que 1, donc 2 450 > 1 980."],
            ),
            EX(
                "exemple-comparer-2",
                "Comparer 7 382 et 7 391",
                [
                    "Les deux nombres ont 4 chiffres, le même chiffre des milliers (7) et le même chiffre des centaines (3).",
                    "Chiffre des dizaines : 8 et 9. Comme 8 < 9, on conclut :",
                    "7 382 < 7 391",
                ],
            ),
            CO(
                "piege",
                "warning",
                "Attention : ne compare pas seulement le dernier chiffre. Le nombre 1 999 est plus petit que 2 000, même si 9 est plus grand que 0.",
            ),
            CO("retenir", "remember", "Le signe < ou > s'ouvre du côté du plus grand nombre : 3 < 5 et 5 > 3."),
        ],
        "ht": [
            P("objectifs", "Lè leson sa a fini, w ap konn li ak ekri yon nonb antye jouk 999 999, di ki valè chak chif genyen, epi konpare de nonb."),
            P("intro", "Yon estad ka resevwa 2 450 moun. Yon lòt estad resevwa 1 980. Ki sa ki pi gwo ? Pou reponn, fò nou konn li ak konpare nonb."),
            H("valeur-titre", "Chak chif gen yon valè dapre plas li"),
            P(
                "valeur",
                "Nan yon nonb, yon chif vo plis oswa mwens dapre plas li. Depi sou bò dwat rive sou bò gòch, nou jwenn inite yo, dizèn yo, santèn yo, apresa milye yo. Nan 4 305, chif 4 la nan plas milye yo: li vo 4 000. Chif 3 la vo 300. Chif 0 la montre pa gen okenn dizèn.",
            ),
            EX(
                "exemple-decomposition",
                "Dekonpoze 4 305",
                ["4 305 = 4 000 + 300 + 0 + 5", "4 milye, 3 santèn, 0 dizèn ak 5 inite", "Nou li: kat mil twa san senk"],
            ),
            P("lire", "Pou li yon gwo nonb, nou koupe l an tranch twa chif, nou kòmanse sou bò dwat. 12 480 li « douz mil kat san katrevenn »."),
            H("comparer-titre", "Konpare de nonb"),
            P(
                "comparer",
                "Pou konpare de nonb, nou konte chif yo anvan: nonb ki gen plis chif la se pi gwo a. Si yo gen menm kantite chif, nou konpare chif yo de gòch pou dwat epi nou kanpe nan premye chif ki pa menm lan.",
            ),
            EX(
                "exemple-comparer-1",
                "Konpare 2 450 ak 1 980",
                ["De nonb yo gen 4 chif chak.", "Nou konpare milye yo: 2 ak 1.", "2 pi gwo pase 1, donk 2 450 > 1 980."],
            ),
            EX(
                "exemple-comparer-2",
                "Konpare 7 382 ak 7 391",
                ["De nonb yo gen 4 chif chak, menm chif milye (7) ak menm chif santèn (3).", "Chif dizèn yo: 8 ak 9. Kòm 8 < 9, nou konkli:", "7 382 < 7 391"],
            ),
            CO("piege", "warning", "Atansyon: pa konpare sèlman dènye chif la. Nonb 1 999 pi piti pase 2 000, menmsi 9 pi gwo pase 0."),
            CO("retenir", "remember", "Siy < oswa > louvri bò nonb ki pi gwo a: 3 < 5 epi 5 > 3."),
        ],
    },
    examples=[
        ExampleCheck("exemple-decomposition", [{"expr": "4000 + 300 + 0 + 5", "equals": 4305, "must_appear": "4305=4000+300+0+5"}]),
        ExampleCheck("exemple-comparer-1", [{"expr": "2450 > 1980", "equals": True, "must_appear": "2450>1980"}]),
        ExampleCheck("exemple-comparer-2", [{"expr": "7382 < 7391", "equals": True, "must_appear": "7382<7391"}]),
    ],
    questions=[
        Q(
            "valeur-du-chiffre",
            "value",
            "c",
            compute="5723 // 100 % 10 * 100",
            prompt={"fr": "Dans le nombre 5 723, quelle est la valeur du chiffre 7 ?", "ht": "Nan nonb 5 723 lan, ki valè chif 7 la ?"},
            choices=[C(7), C(70), C(700), C(7000)],
            explanation={"fr": "Le 7 est à la place des centaines : il vaut 7 × 100 = 700.", "ht": "Chif 7 la nan plas santèn yo: li vo 7 × 100 = 700."},
        ),
        Q(
            "ecrire-en-chiffres",
            "value",
            "b",
            compute="32 * 1000 + 506",
            prompt={
                "fr": "Comment écrit-on « trente-deux mille cinq cent six » en chiffres ?",
                "ht": "Ki jan nou ekri « trant-de mil senk san sis » ak chif ?",
            },
            choices=[C(32056), C(32506), C(3256), C(32560)],
            explanation={"fr": "32 milliers et 506 unités : 32 506.", "ht": "32 milye ak 506 inite: 32 506."},
        ),
        Q(
            "comparer-deux-nombres",
            "truth",
            "a",
            prompt={"fr": "Compare 6 054 et 6 540. Quelle réponse est juste ?", "ht": "Konpare 6 054 ak 6 540. Ki repons ki bon ?"},
            choices=[
                C(expr="6054 < 6540", fr="6 054 < 6 540", ht="6 054 < 6 540"),
                C(expr="6054 > 6540", fr="6 054 > 6 540", ht="6 054 > 6 540"),
                C(expr="6054 == 6540", fr="6 054 = 6 540", ht="6 054 = 6 540"),
                C(expr="False", fr="On ne peut pas savoir", ht="Nou pa ka konnen"),
            ],
            explanation={
                "fr": "Les deux nombres ont 4 chiffres et le même chiffre des milliers (6). Aux centaines, 0 < 5. Donc 6 054 < 6 540.",
                "ht": "De nonb yo gen 4 chif epi yo gen menm chif milye (6). Nan santèn yo, 0 < 5. Donk 6 054 < 6 540.",
            },
        ),
        Q(
            "plus-grand-nombre",
            "value",
            "b",
            compute="max(9870, 10002, 9999, 987)",
            prompt={
                "fr": "Quel est le plus grand de ces nombres : 9 870, 10 002, 9 999, 987 ?",
                "ht": "Ki nonb ki pi gwo nan nonb sa yo: 9 870, 10 002, 9 999, 987 ?",
            },
            choices=[C(9870), C(10002), C(9999), C(987)],
            explanation={
                "fr": "10 002 a 5 chiffres, les autres en ont 4 ou moins : c'est le plus grand.",
                "ht": "10 002 gen 5 chif, lòt yo gen 4 oswa mwens: se li ki pi gwo a.",
            },
        ),
        Q(
            "chiffre-des-centaines",
            "value",
            "b",
            compute="3480 // 100 % 10",
            prompt={"fr": "Quel est le chiffre des centaines dans 3 480 ?", "ht": "Ki chif santèn yo nan 3 480 ?"},
            choices=[C(3), C(4), C(8), C(0)],
            explanation={
                "fr": "3 480 = 3 milliers + 4 centaines + 8 dizaines. Le chiffre des centaines est 4.",
                "ht": "3 480 = 3 milye + 4 santèn + 8 dizèn. Chif santèn yo se 4.",
            },
        ),
    ],
)
