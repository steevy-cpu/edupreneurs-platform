from ..lib import CO, EX, C, ExampleCheck, H, Lesson, P, Q

LESSON = Lesson(
    slug="additionner-soustraire",
    position=2,
    titles={"fr": "Additionner et soustraire", "ht": "Fè adisyon ak soustraksyon"},
    objectives={
        "fr": [
            "Additionner et soustraire des nombres entiers en colonnes.",
            "Calculer dans sa tête en s'appuyant sur un nombre rond.",
            "Vérifier une soustraction avec une addition.",
        ],
        "ht": [
            "Fè adisyon ak soustraksyon ak nonb antye an kolòn.",
            "Kalkile nan tèt ou lè w sèvi ak yon nonb won.",
            "Verifye yon soustraksyon ak yon adisyon.",
        ],
    },
    refs=[
        {
            "source": "S1",
            "locator": "p. imprimée 38 (PDF p. 39), unité « Nombres et calculs », 7e année : « Donner un sens aux opérations sur les nombres » ; « Savoir effectuer des opérations (addition, soustraction, multiplication et division) sous les trois formes de calcul (mental, à la main et instrumentée) »",
            "relation": "partial",
            "note": "Calcul mental et à la main seulement ; le calcul instrumenté (calculatrice) n'est pas traité.",
        },
        {
            "source": "S2",
            "locator": "PDF p. 6 (décembre, semaine 3), Algèbre 2.1.1 « Calculer mentalement et par écrit des sommes, produits, différences, quotients d'entiers naturels »",
            "relation": "direct",
            "note": "Programme à compétences minimales 2019-2020.",
        },
    ],
    blocks={
        "fr": [
            P(
                "objectifs",
                "À la fin de cette leçon, tu sauras additionner et soustraire des nombres entiers en colonnes et dans ta tête, et vérifier ton résultat.",
            ),
            P(
                "intro",
                "Une école a 348 élèves le matin. À midi, 275 autres élèves arrivent pour une fête. Combien d'élèves y a-t-il en tout ? On additionne : 348 + 275.",
            ),
            P(
                "sens",
                "Additionner, c'est réunir des quantités : le résultat s'appelle la somme. Soustraire, c'est enlever une quantité ou chercher l'écart entre deux nombres : le résultat s'appelle la différence.",
            ),
            H("posee-titre", "Calculer en colonnes"),
            P(
                "posee",
                "On écrit les nombres l'un sous l'autre : unités sous unités, dizaines sous dizaines, centaines sous centaines. On calcule en commençant par la droite. Quand une colonne dépasse 9 dans une addition, on retient 1 dans la colonne suivante.",
            ),
            EX(
                "exemple-addition",
                "Calculer 348 + 275",
                [
                    "Unités : 8 + 5 = 13. On écrit 3 et on retient 1.",
                    "Dizaines : 4 + 7 + 1 = 12. On écrit 2 et on retient 1.",
                    "Centaines : 3 + 2 + 1 = 6.",
                    "348 + 275 = 623",
                ],
            ),
            EX(
                "exemple-soustraction",
                "Calculer 623 − 275",
                [
                    "Unités : 3 − 5 est impossible. On échange une dizaine contre 10 unités : 13 − 5 = 8.",
                    "Dizaines : il reste 1 dizaine. On échange une centaine contre 10 dizaines : 11 − 7 = 4.",
                    "Centaines : il reste 5 centaines. 5 − 2 = 3.",
                    "623 − 275 = 348",
                ],
            ),
            H("mental-titre", "Calculer dans sa tête"),
            P("mental", "Pour calculer vite, on peut s'appuyer sur un nombre rond. Pour 98 + 47, on part de 100, car 98 est tout près de 100."),
            EX(
                "exemple-mental",
                "Calculer 98 + 47 dans sa tête",
                ["98 est proche de 100 : 100 + 47 = 147.", "On a ajouté 2 de trop (100 au lieu de 98) : 147 − 2 = 145.", "98 + 47 = 145"],
            ),
            CO("verification", "tip", "Vérifie une soustraction avec une addition : si 623 − 275 = 348, alors 348 + 275 doit donner 623."),
            CO("piege", "warning", "Attention : avec des entiers naturels, on enlève toujours le petit nombre au grand nombre. 275 − 623 n'est pas possible."),
            CO(
                "retenir",
                "remember",
                "Somme : résultat d'une addition. Différence : résultat d'une soustraction. L'addition et la soustraction sont des opérations contraires.",
            ),
        ],
        "ht": [
            P("objectifs", "Lè leson sa a fini, w ap konn fè adisyon ak soustraksyon ak nonb antye an kolòn ak nan tèt ou, epi verifye rezilta w."),
            P(
                "intro",
                "Yon lekòl gen 348 elèv nan maten. Nan midi, 275 lòt elèv vini pou yon fèt. Konbyen elèv ki genyen an total ? Nou fè yon adisyon: 348 + 275.",
            ),
            P(
                "sens",
                "Adisyone, se rasanble kantite yo: rezilta a rele som. Soustraksyon, se wete yon kantite oswa chèche diferans ant de nonb: rezilta a rele diferans.",
            ),
            H("posee-titre", "Kalkile an kolòn"),
            P(
                "posee",
                "Nou ekri nonb yo youn anba lòt: inite anba inite, dizèn anba dizèn, santèn anba santèn. Nou kalkile kòmanse sou bò dwat. Lè yon kolòn depase 9 nan yon adisyon, nou retni 1 nan kolòn ki vini apre a.",
            ),
            EX(
                "exemple-addition",
                "Kalkile 348 + 275",
                [
                    "Inite: 8 + 5 = 13. Nou ekri 3 epi nou retni 1.",
                    "Dizèn: 4 + 7 + 1 = 12. Nou ekri 2 epi nou retni 1.",
                    "Santèn: 3 + 2 + 1 = 6.",
                    "348 + 275 = 623",
                ],
            ),
            EX(
                "exemple-soustraction",
                "Kalkile 623 − 275",
                [
                    "Inite: 3 − 5 pa posib. Nou chanje yon dizèn pou 10 inite: 13 − 5 = 8.",
                    "Dizèn: li rete 1 dizèn. Nou chanje yon santèn pou 10 dizèn: 11 − 7 = 4.",
                    "Santèn: li rete 5 santèn. 5 − 2 = 3.",
                    "623 − 275 = 348",
                ],
            ),
            H("mental-titre", "Kalkile nan tèt ou"),
            P("mental", "Pou kalkile vit, nou ka ponye sou yon nonb won. Pou 98 + 47, nou pati de 100, paske 98 toupre 100."),
            EX(
                "exemple-mental",
                "Kalkile 98 + 47 nan tèt ou",
                ["98 toupre 100: 100 + 47 = 147.", "Nou ajoute 2 twòp (100 olye de 98): 147 − 2 = 145.", "98 + 47 = 145"],
            ),
            CO("verification", "tip", "Verifye yon soustraksyon ak yon adisyon: si 623 − 275 = 348, alò 348 + 275 dwe bay 623."),
            CO("piege", "warning", "Atansyon: ak nonb antye natirèl, nou toujou wete ti nonb la nan gwo nonb la. 275 − 623 pa posib."),
            CO("retenir", "remember", "Som: rezilta yon adisyon. Diferans: rezilta yon soustraksyon. Adisyon ak soustraksyon se operasyon ki kontrè."),
        ],
    },
    examples=[
        ExampleCheck(
            "exemple-addition",
            [
                {"expr": "8 + 5", "equals": 13, "must_appear": "8+5=13"},
                {"expr": "4 + 7 + 1", "equals": 12, "must_appear": "4+7+1=12"},
                {"expr": "3 + 2 + 1", "equals": 6, "must_appear": "3+2+1=6"},
                {"expr": "348 + 275", "equals": 623, "must_appear": "348+275=623"},
            ],
        ),
        ExampleCheck(
            "exemple-soustraction",
            [
                {"expr": "13 - 5", "equals": 8, "must_appear": "13−5=8"},
                {"expr": "11 - 7", "equals": 4, "must_appear": "11−7=4"},
                {"expr": "5 - 2", "equals": 3, "must_appear": "5−2=3"},
                {"expr": "623 - 275", "equals": 348, "must_appear": "623−275=348"},
            ],
        ),
        ExampleCheck(
            "exemple-mental",
            [
                {"expr": "100 + 47", "equals": 147, "must_appear": "100+47=147"},
                {"expr": "147 - 2", "equals": 145, "must_appear": "147−2=145"},
                {"expr": "98 + 47", "equals": 145, "must_appear": "98+47=145"},
            ],
        ),
    ],
    questions=[
        Q(
            "addition-posee",
            "value",
            "b",
            compute="456 + 378",
            prompt={"fr": "Calcule : 456 + 378", "ht": "Kalkile: 456 + 378"},
            choices=[C(824), C(834), C(744), C(934)],
            explanation={
                "fr": "Unités : 6 + 8 = 14, on écrit 4 et on retient 1. Dizaines : 5 + 7 + 1 = 13, on écrit 3 et on retient 1. Centaines : 4 + 3 + 1 = 8. Résultat : 834.",
                "ht": "Inite: 6 + 8 = 14, nou ekri 4 epi nou retni 1. Dizèn: 5 + 7 + 1 = 13, nou ekri 3 epi nou retni 1. Santèn: 4 + 3 + 1 = 8. Rezilta: 834.",
            },
        ),
        Q(
            "soustraction-posee",
            "value",
            "c",
            compute="702 - 345",
            prompt={"fr": "Calcule : 702 − 345", "ht": "Kalkile: 702 − 345"},
            choices=[C(457), C(367), C(357), C(443)],
            explanation={
                "fr": "On vérifie avec l'addition : 357 + 345 = 702. Donc 702 − 345 = 357.",
                "ht": "Nou verifye ak adisyon: 357 + 345 = 702. Donk 702 − 345 = 357.",
            },
        ),
        Q(
            "probleme-camion",
            "value",
            "b",
            compute="1250 - 480",
            prompt={
                "fr": "Un camion transporte 1 250 kg de maïs. Il en décharge 480 kg. Combien de kilogrammes reste-t-il dans le camion ?",
                "ht": "Yon kamyon pote 1 250 kg mayi. Li dechaje 480 kg. Konbyen kilogram ki rete nan kamyon an ?",
            },
            choices=[
                C(730, fr="730 kg", ht="730 kg"),
                C(770, fr="770 kg", ht="770 kg"),
                C(1730, fr="1 730 kg", ht="1 730 kg"),
                C(870, fr="870 kg", ht="870 kg"),
            ],
            explanation={"fr": "On soustrait : 1 250 − 480 = 770. Il reste 770 kg.", "ht": "Nou soustrè: 1 250 − 480 = 770. Li rete 770 kg."},
        ),
        Q(
            "calcul-mental",
            "value",
            "b",
            compute="99 + 36",
            prompt={"fr": "Calcule dans ta tête : 99 + 36", "ht": "Kalkile nan tèt ou: 99 + 36"},
            choices=[C(125), C(135), C(145), C(136)],
            explanation={"fr": "99 + 36 = 100 + 36 − 1 = 136 − 1 = 135.", "ht": "99 + 36 = 100 + 36 − 1 = 136 − 1 = 135."},
        ),
        Q(
            "verifier-soustraction",
            "truth",
            "a",
            prompt={"fr": "Quelle égalité permet de vérifier que 540 − 260 = 280 ?", "ht": "Ki egalite ki pèmèt verifye ke 540 − 260 = 280 ?"},
            choices=[
                C(expr="280 + 260 == 540", fr="280 + 260 = 540", ht="280 + 260 = 540"),
                C(expr="280 - 260 == 540", fr="280 − 260 = 540", ht="280 − 260 = 540"),
                C(expr="540 + 260 == 280", fr="540 + 260 = 280", ht="540 + 260 = 280"),
                C(expr="260 - 280 == 540", fr="260 − 280 = 540", ht="260 − 280 = 540"),
            ],
            explanation={
                "fr": "Pour vérifier une soustraction, on additionne la différence et le petit nombre : 280 + 260 = 540.",
                "ht": "Pou verifye yon soustraksyon, nou adisyone diferans lan ak ti nonb la: 280 + 260 = 540.",
            },
        ),
    ],
)
