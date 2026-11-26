from ..lib import CO, EX, C, ExampleCheck, H, Lesson, P, Q

LESSON = Lesson(
    slug="multiplier-diviser-10-100-1000",
    position=4,
    titles={"fr": "Multiplier et diviser par 10, 100, 1 000", "ht": "Miltipliye ak divize pa 10, 100, 1 000"},
    objectives={
        "fr": [
            "Multiplier un nombre entier par 10, 100 ou 1 000.",
            "Diviser par 10, 100 ou 1 000 un nombre qui se termine par assez de zéros.",
            "Changer d'unité de mesure (m en cm, km en m) avec ces calculs.",
        ],
        "ht": [
            "Miltipliye yon nonb antye pa 10, 100 oswa 1 000.",
            "Divize pa 10, 100 oswa 1 000 yon nonb ki fini ak ase zewo.",
            "Chanje inite mezi (m an cm, km an m) ak kalkil sa yo.",
        ],
    },
    refs=[
        {
            "source": "S1",
            "locator": "p. imprimée 38 (PDF p. 39), 7e année, unité « Nombres et calculs » : sous-objectif sur la multiplication et la division d'un nombre décimal par des puissances de 10 (et par 0,1 ; 0,01 ; 0,001)",
            "relation": "partial",
            "note": "Seulement les entiers naturels : la multiplication et la division de nombres décimaux (et par 0,1 ; 0,01 ; 0,001) sont renvoyées à Content-02B.",
        },
        {
            "source": "S2",
            "locator": "PDF p. 6 (décembre, semaine 3), code Mesures 1.1.2 : passage d'une unité de mesure à une autre",
            "relation": "context",
            "note": "Aucun item de ce programme ne traite directement de ×10/×100/×1 000 ; le lien se fait par les conversions d'unités.",
        },
    ],
    blocks={
        "fr": [
            P(
                "objectifs",
                "À la fin de cette leçon, tu sauras multiplier un nombre entier par 10, 100 ou 1 000, et diviser par 10, 100 ou 1 000 un nombre qui se termine par assez de zéros.",
            ),
            P(
                "intro",
                "1 mètre fait 100 centimètres. Pour changer 7 mètres en centimètres, on multiplie 7 par 100. Les multiplications et les divisions par 10, 100 et 1 000 se font très vite : il suffit de bien connaître la valeur des chiffres.",
            ),
            H("multiplier-titre", "Multiplier par 10, 100 ou 1 000"),
            P(
                "multiplier",
                "Quand on multiplie par 10, chaque chiffre vaut 10 fois plus : il avance d'une place vers la gauche. On écrit un zéro à la droite du nombre. Par 100, on écrit deux zéros. Par 1 000, on écrit trois zéros.",
            ),
            EX("exemple-multiplier", "Multiplier 36", ["36 × 10 = 360", "36 × 100 = 3 600", "36 × 1 000 = 36 000"]),
            H("diviser-titre", "Diviser par 10, 100 ou 1 000"),
            P(
                "diviser",
                "Diviser par 10, c'est l'inverse : chaque chiffre vaut 10 fois moins. Si le nombre se termine par un zéro, on enlève ce zéro. Par 100, on enlève deux zéros. Par 1 000, on enlève trois zéros.",
            ),
            EX("exemple-diviser", "Diviser 4 500 et 12 000", ["4 500 ÷ 10 = 450", "4 500 ÷ 100 = 45", "12 000 ÷ 1 000 = 12"]),
            EX(
                "exemple-unites",
                "Changer d'unité de mesure",
                ["1 m = 100 cm, donc 7 m = 7 × 100 = 700 cm.", "1 km = 1 000 m, donc 3 km = 3 × 1 000 = 3 000 m.", "900 cm = 900 ÷ 100 = 9 m."],
            ),
            CO(
                "piege",
                "warning",
                "Attention : « ajouter un zéro » ne marche que pour multiplier un nombre entier par 10. 7 × 10 = 70, mais 7 + 10 = 17. Et on ne peut enlever des zéros que s'ils sont à la fin du nombre : 4 050 ÷ 100 n'est pas un nombre entier.",
            ),
            CO(
                "retenir",
                "remember",
                "× 10, × 100, × 1 000 : on ajoute 1, 2 ou 3 zéros. ÷ 10, ÷ 100, ÷ 1 000 : on enlève 1, 2 ou 3 zéros, quand il y en a assez à la fin.",
            ),
        ],
        "ht": [
            P(
                "objectifs",
                "Lè leson sa a fini, w ap konn miltipliye yon nonb antye pa 10, 100 oswa 1 000, epi divize pa 10, 100 oswa 1 000 yon nonb ki fini ak ase zewo.",
            ),
            P(
                "intro",
                "1 mèt fè 100 santimèt. Pou chanje 7 mèt an santimèt, nou miltipliye 7 pa 100. Miltiplikasyon ak divizyon pa 10, 100 ak 1 000 fèt byen vit: se sèlman pou konn valè chif yo byen.",
            ),
            H("multiplier-titre", "Miltipliye pa 10, 100 oswa 1 000"),
            P(
                "multiplier",
                "Lè nou miltipliye pa 10, chak chif vo 10 fwa plis: li avanse yon plas sou bò gòch. Nou ekri yon zewo sou bò dwat nonb lan. Pa 100, nou ekri de zewo. Pa 1 000, nou ekri twa zewo.",
            ),
            EX("exemple-multiplier", "Miltipliye 36", ["36 × 10 = 360", "36 × 100 = 3 600", "36 × 1 000 = 36 000"]),
            H("diviser-titre", "Divize pa 10, 100 oswa 1 000"),
            P(
                "diviser",
                "Divize pa 10, se kontrè a: chak chif vo 10 fwa mwens. Si nonb lan fini ak yon zewo, nou wete zewo sa a. Pa 100, nou wete de zewo. Pa 1 000, nou wete twa zewo.",
            ),
            EX("exemple-diviser", "Divize 4 500 ak 12 000", ["4 500 ÷ 10 = 450", "4 500 ÷ 100 = 45", "12 000 ÷ 1 000 = 12"]),
            EX(
                "exemple-unites",
                "Chanje inite mezi",
                ["1 m = 100 cm, donk 7 m = 7 × 100 = 700 cm.", "1 km = 1 000 m, donk 3 km = 3 × 1 000 = 3 000 m.", "900 cm = 900 ÷ 100 = 9 m."],
            ),
            CO(
                "piege",
                "warning",
                "Atansyon: « ajoute yon zewo » mache sèlman pou miltipliye yon nonb antye pa 10. 7 × 10 = 70, men 7 + 10 = 17. Epi nou pa ka wete zewo si yo pa nan fen nonb lan: 4 050 ÷ 100 pa yon nonb antye.",
            ),
            CO(
                "retenir",
                "remember",
                "× 10, × 100, × 1 000: nou ajoute 1, 2 oswa 3 zewo. ÷ 10, ÷ 100, ÷ 1 000: nou wete 1, 2 oswa 3 zewo, lè gen ase nan fen nonb lan.",
            ),
        ],
    },
    examples=[
        ExampleCheck(
            "exemple-multiplier",
            [
                {"expr": "36 * 10", "equals": 360, "must_appear": "36×10=360"},
                {"expr": "36 * 100", "equals": 3600, "must_appear": "36×100=3600"},
                {"expr": "36 * 1000", "equals": 36000, "must_appear": "36×1000=36000"},
            ],
        ),
        ExampleCheck(
            "exemple-diviser",
            [
                {"expr": "4500 // 10", "equals": 450, "must_appear": "4500÷10=450"},
                {"expr": "4500 // 100", "equals": 45, "must_appear": "4500÷100=45"},
                {"expr": "12000 // 1000", "equals": 12, "must_appear": "12000÷1000=12"},
                {"expr": "4500 % 10 == 0 and 4500 % 100 == 0", "equals": True, "must_appear": "4500÷100"},
            ],
        ),
        ExampleCheck(
            "exemple-unites",
            [
                {"expr": "7 * 100", "equals": 700, "must_appear": "7×100=700"},
                {"expr": "3 * 1000", "equals": 3000, "must_appear": "3×1000=3000"},
                {"expr": "900 // 100", "equals": 9, "must_appear": "900÷100=9"},
            ],
        ),
    ],
    questions=[
        Q(
            "fois-100",
            "value",
            "b",
            place=2,
            math="35 × 100",
            compute="35 * 100",
            prompt={"fr": "Calcule : 35 × 100", "ht": "Kalkile: 35 × 100"},
            choices=[C(350), C(3500), C(35000), C(135)],
            explanation={
                "fr": "Multiplier par 100, c'est ajouter deux zéros : 35 × 100 = 3 500.",
                "ht": "Miltipliye pa 100, se ajoute de zewo: 35 × 100 = 3 500.",
            },
        ),
        Q(
            "divise-10",
            "value",
            "b",
            place=4,
            math="6 200 ÷ 10",
            compute="6200 // 10",
            prompt={"fr": "Calcule : 6 200 ÷ 10", "ht": "Kalkile: 6 200 ÷ 10"},
            choices=[C(62), C(620), C(6200), C(62000)],
            explanation={"fr": "Diviser par 10, c'est enlever un zéro : 6 200 ÷ 10 = 620.", "ht": "Divize pa 10, se wete yon zewo: 6 200 ÷ 10 = 620."},
        ),
        Q(
            "convertir-km",
            "value",
            "c",
            place=1,
            compute="8 * 1000",
            prompt={"fr": "Combien de mètres y a-t-il dans 8 km ?", "ht": "Konbyen mèt ki genyen nan 8 km ?"},
            choices=[C(80, fr="80 m", ht="80 m"), C(800, fr="800 m", ht="800 m"), C(8000, fr="8 000 m", ht="8 000 m"), C(80000, fr="80 000 m", ht="80 000 m")],
            explanation={"fr": "1 km = 1 000 m, donc 8 km = 8 × 1 000 = 8 000 m.", "ht": "1 km = 1 000 m, donk 8 km = 8 × 1 000 = 8 000 m."},
        ),
        Q(
            "paquets-de-feuilles",
            "value",
            "b",
            place=3,
            compute="24 * 100",
            prompt={
                "fr": "Un paquet contient 100 feuilles. Combien de feuilles y a-t-il dans 24 paquets ?",
                "ht": "Yon pake gen 100 fèy. Konbyen fèy ki genyen nan 24 pake ?",
            },
            choices=[C(240), C(2400), C(24000), C(124)],
            explanation={"fr": "24 × 100 = 2 400 feuilles.", "ht": "24 × 100 = 2 400 fèy."},
        ),
        Q(
            "divise-1000",
            "value",
            "b",
            place=2,
            math="48 000 ÷ 1 000",
            compute="48000 // 1000",
            prompt={"fr": "Calcule : 48 000 ÷ 1 000", "ht": "Kalkile: 48 000 ÷ 1 000"},
            choices=[C(480), C(48), C(4800), C(8)],
            explanation={
                "fr": "Diviser par 1 000, c'est enlever trois zéros : 48 000 ÷ 1 000 = 48.",
                "ht": "Divize pa 1 000, se wete twa zewo: 48 000 ÷ 1 000 = 48.",
            },
        ),
    ],
)
