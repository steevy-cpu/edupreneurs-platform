from ..lib import CO, EX, C, ExampleCheck, H, Lesson, P, Q

LESSON = Lesson(
    slug="multiplier-diviser",
    position=3,
    titles={"fr": "Multiplier et diviser", "ht": "Miltipliye ak divize"},
    objectives={
        "fr": [
            "Multiplier un nombre entier par un nombre à un chiffre.",
            "Faire une division avec reste et nommer dividende, diviseur, quotient et reste.",
            "Vérifier une division avec la multiplication.",
        ],
        "ht": [
            "Miltipliye yon nonb antye pa yon nonb ki gen yon sèl chif.",
            "Fè yon divizyon ki gen rès epi non dividand, divizè, kosyan ak rès.",
            "Verifye yon divizyon ak miltiplikasyon.",
        ],
    },
    refs=[
        {
            "source": "S1",
            "locator": "p. imprimée 38 (PDF p. 39), 7e année, unité « Nombres et calculs » : sous-objectifs sur l'exécution des quatre opérations, puis sur le quotient, les multiples et les diviseurs d'entiers",
            "relation": "partial",
            "note": "Multiplication par un nombre à un chiffre et division avec reste sur de petits nombres seulement ; division posée par un diviseur à plusieurs chiffres non traitée.",
        },
        {
            "source": "S2",
            "locator": "PDF p. 6 (décembre, semaine 3), code Algèbre 2.1.1 : calcul de sommes, différences, produits et quotients d'entiers naturels",
            "relation": "direct",
            "note": "Programme à compétences minimales 2019-2020.",
        },
    ],
    blocks={
        "fr": [
            P(
                "objectifs",
                "À la fin de cette leçon, tu sauras multiplier un nombre par un nombre à un chiffre, faire une division avec reste, et vérifier ton résultat.",
            ),
            P("intro", "Une marchande range 12 mangues dans chaque panier. Elle a 6 paniers. Combien de mangues a-t-elle en tout ? On calcule 6 × 12."),
            P(
                "sens-fois",
                "Multiplier, c'est additionner plusieurs fois le même nombre : 6 × 12, c'est 12 + 12 + 12 + 12 + 12 + 12. Le résultat s'appelle le produit. On gagne du temps en connaissant bien les tables de multiplication.",
            ),
            EX(
                "exemple-multiplication",
                "Calculer 6 × 12",
                ["Unités : 6 × 2 = 12. On écrit 2 et on retient 1.", "Dizaines : 6 × 1 = 6, puis 6 + 1 = 7.", "6 × 12 = 72"],
            ),
            H("division-titre", "Diviser"),
            P(
                "division",
                "Diviser, c'est partager en parts égales ou chercher combien de fois un nombre est contenu dans un autre. Dans 17 ÷ 5, le nombre 17 est le dividende, 5 est le diviseur et le résultat est le quotient. Parfois il reste quelque chose : c'est le reste.",
            ),
            EX(
                "exemple-division-1",
                "Calculer 17 ÷ 5",
                ["Dans 17, combien de fois 5 ? 3 fois, car 5 × 3 = 15.", "Il reste 17 − 15 = 2.", "17 = 5 × 3 + 2 : le quotient est 3 et le reste est 2."],
            ),
            P("reste", "Le reste est toujours plus petit que le diviseur. Si le reste est 0, la division est exacte."),
            EX(
                "exemple-division-2",
                "Partager 85 crayons dans 4 boîtes",
                [
                    "4 × 20 = 80, et il reste 85 − 80 = 5 crayons.",
                    "Dans 5, il y a encore 1 fois 4 : 4 × 1 = 4, et il reste 1.",
                    "Chaque boîte reçoit 20 + 1 = 21 crayons et il reste 1 crayon : 85 = 4 × 21 + 1.",
                ],
            ),
            CO("verification", "tip", "Vérifie une division : diviseur × quotient + reste doit donner le dividende."),
            CO("piege", "warning", "Attention : on ne peut pas diviser par 0."),
            CO(
                "retenir",
                "remember",
                "Produit : résultat d'une multiplication. Quotient : résultat d'une division. Dividende = diviseur × quotient + reste, avec un reste plus petit que le diviseur.",
            ),
        ],
        "ht": [
            P(
                "objectifs",
                "Lè leson sa a fini, w ap konn miltipliye yon nonb pa yon nonb ki gen yon sèl chif, fè yon divizyon ki gen rès, epi verifye rezilta w.",
            ),
            P("intro", "Yon machann ranje 12 mango nan chak panye. Li gen 6 panye. Konbyen mango li genyen an total ? Nou kalkile 6 × 12."),
            P(
                "sens-fois",
                "Miltipliye, se adisyone menm nonb la plizyè fwa: 6 × 12, se 12 + 12 + 12 + 12 + 12 + 12. Rezilta a rele pwodui. Nou genyen tan lè nou konn tab miltiplikasyon yo byen.",
            ),
            EX(
                "exemple-multiplication",
                "Kalkile 6 × 12",
                ["Inite: 6 × 2 = 12. Nou ekri 2 epi nou retni 1.", "Dizèn: 6 × 1 = 6, answit 6 + 1 = 7.", "6 × 12 = 72"],
            ),
            H("division-titre", "Divize"),
            P(
                "division",
                "Divize, se pataje an pati egal oswa chèche konbyen fwa yon nonb nan yon lòt. Nan 17 ÷ 5, nonb 17 la se dividand lan, 5 la se divizè a, epi rezilta a se kosyan an. Pafwa gen yon bagay ki rete: se rès la.",
            ),
            EX(
                "exemple-division-1",
                "Kalkile 17 ÷ 5",
                ["Nan 17, konbyen fwa 5 ? 3 fwa, paske 5 × 3 = 15.", "Li rete 17 − 15 = 2.", "17 = 5 × 3 + 2: kosyan an se 3 epi rès la se 2."],
            ),
            P("reste", "Rès la toujou pi piti pase divizè a. Si rès la se 0, divizyon an egzat."),
            EX(
                "exemple-division-2",
                "Pataje 85 kreyon nan 4 bwat",
                [
                    "4 × 20 = 80, epi li rete 85 − 80 = 5 kreyon.",
                    "Nan 5, gen ankò 1 fwa 4: 4 × 1 = 4, epi li rete 1.",
                    "Chak bwat resevwa 20 + 1 = 21 kreyon epi li rete 1 kreyon: 85 = 4 × 21 + 1.",
                ],
            ),
            CO("verification", "tip", "Verifye yon divizyon: divizè × kosyan + rès dwe bay dividand lan."),
            CO("piege", "warning", "Atansyon: nou pa ka divize pa 0."),
            CO(
                "retenir",
                "remember",
                "Pwodui: rezilta yon miltiplikasyon. Kosyan: rezilta yon divizyon. Dividand = divizè × kosyan + rès, ak yon rès ki pi piti pase divizè a.",
            ),
        ],
    },
    examples=[
        ExampleCheck(
            "exemple-multiplication",
            [
                {"expr": "6 * 2", "equals": 12, "must_appear": "6×2=12"},
                {"expr": "6 * 1", "equals": 6, "must_appear": "6×1=6"},
                {"expr": "6 + 1", "equals": 7, "must_appear": "6+1=7"},
                {"expr": "6 * 12", "equals": 72, "must_appear": "6×12=72"},
            ],
        ),
        ExampleCheck(
            "exemple-division-1",
            [
                {"expr": "5 * 3", "equals": 15, "must_appear": "5×3=15"},
                {"expr": "17 - 15", "equals": 2, "must_appear": "17−15=2"},
                {"expr": "5 * 3 + 2", "equals": 17, "must_appear": "17=5×3+2"},
                {"expr": "17 // 5", "equals": 3, "must_appear": "3"},
                {"expr": "17 % 5", "equals": 2, "must_appear": "2"},
            ],
        ),
        ExampleCheck(
            "exemple-division-2",
            [
                {"expr": "4 * 20", "equals": 80, "must_appear": "4×20=80"},
                {"expr": "85 - 80", "equals": 5, "must_appear": "85−80=5"},
                {"expr": "4 * 21 + 1", "equals": 85, "must_appear": "85=4×21+1"},
                {"expr": "85 // 4", "equals": 21, "must_appear": "21"},
                {"expr": "85 % 4", "equals": 1, "must_appear": "1"},
            ],
        ),
    ],
    questions=[
        Q(
            "multiplication",
            "value",
            "b",
            place=4,
            math="8 × 14",
            compute="8 * 14",
            prompt={"fr": "Calcule : 8 × 14", "ht": "Kalkile: 8 × 14"},
            choices=[C(102), C(112), C(122), C(22)],
            explanation={
                "fr": "8 × 4 = 32 : on écrit 2 et on retient 3. 8 × 1 = 8, puis 8 + 3 = 11. Donc 8 × 14 = 112.",
                "ht": "8 × 4 = 32: nou ekri 2 epi nou retni 3. 8 × 1 = 8, answit 8 + 3 = 11. Donk 8 × 14 = 112.",
            },
        ),
        Q(
            "probleme-chaises",
            "value",
            "b",
            place=1,
            compute="9 * 15",
            prompt={
                "fr": "Une salle a 9 rangées de 15 chaises. Combien y a-t-il de chaises en tout ?",
                "ht": "Yon sal gen 9 ranje ki gen 15 chèz chak. Konbyen chèz ki genyen an total ?",
            },
            choices=[C(125), C(135), C(145), C(24)],
            explanation={"fr": "On calcule 9 × 15 = 135. Il y a 135 chaises.", "ht": "Nou kalkile 9 × 15 = 135. Gen 135 chèz."},
        ),
        Q(
            "quotient",
            "value",
            "b",
            place=2,
            math="56 ÷ 7",
            compute="56 // 7",
            prompt={"fr": "Quel est le quotient de 56 ÷ 7 ?", "ht": "Ki kosyan 56 ÷ 7 la ?"},
            choices=[C(7), C(8), C(9), C(49)],
            explanation={"fr": "7 × 8 = 56, donc 56 ÷ 7 = 8.", "ht": "7 × 8 = 56, donk 56 ÷ 7 = 8."},
        ),
        Q(
            "reste-division",
            "value",
            "b",
            place=3,
            compute="47 % 6",
            prompt={"fr": "On divise 47 par 6. Quel est le reste ?", "ht": "Nou divize 47 pa 6. Ki rès la ?"},
            choices=[C(1), C(5), C(6), C(7)],
            explanation={
                "fr": "6 × 7 = 42 et 47 − 42 = 5. Le quotient est 7 et le reste est 5.",
                "ht": "6 × 7 = 42 epi 47 − 42 = 5. Kosyan an se 7 epi rès la se 5.",
            },
        ),
        Q(
            "egalite-division",
            "truth",
            "a",
            place=1,
            prompt={
                "fr": "La division de 29 par 4 donne un quotient de 7 et un reste de 1. Quelle égalité est vraie ?",
                "ht": "Divizyon 29 pa 4 bay yon kosyan 7 ak yon rès 1. Ki egalite ki vre ?",
            },
            choices=[
                C(expr="29 == 4 * 7 + 1", fr="29 = 4 × 7 + 1", ht="29 = 4 × 7 + 1"),
                C(expr="29 == 4 * 7 - 1", fr="29 = 4 × 7 − 1", ht="29 = 4 × 7 − 1"),
                C(expr="29 == 7 * 1 + 4", fr="29 = 7 × 1 + 4", ht="29 = 7 × 1 + 4"),
                C(expr="29 == 4 * 7", fr="29 = 4 × 7", ht="29 = 4 × 7"),
            ],
            explanation={"fr": "Dividende = diviseur × quotient + reste : 4 × 7 + 1 = 29.", "ht": "Dividand = divizè × kosyan + rès: 4 × 7 + 1 = 29."},
        ),
    ],
)
