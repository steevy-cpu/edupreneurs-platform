from ..lib import CO, EX, C, ExampleCheck, H, Lesson, P, Q

LESSON = Lesson(
    slug="multiples-diviseurs",
    position=5,
    titles={"fr": "Multiples et diviseurs", "ht": "Miltip ak divizè"},
    objectives={
        "fr": [
            "Reconnaître un multiple d'un nombre avec sa table de multiplication.",
            "Trouver tous les diviseurs d'un petit nombre.",
            "Dire quand une division tombe juste (reste égal à 0).",
        ],
        "ht": [
            "Rekonèt yon miltip yon nonb ak tab miltiplikasyon li.",
            "Jwenn tout divizè yon ti nonb.",
            "Di ki lè yon divizyon egzat (rès la egal ak 0).",
        ],
    },
    refs=[
        {
            "source": "S1",
            "locator": "p. imprimée 38 (PDF p. 39), unité « Nombres et calculs », 7e année : « Quotient, multiples et diviseurs de nombres entiers »",
            "relation": "direct",
            "note": "Limité aux petits nombres ; nombres premiers, PGCD et PPCM relèvent de la 9e année dans ce programme et ne sont pas traités.",
        },
        {
            "source": "S2",
            "locator": "PDF p. 9 (janvier, semaine 3), Algèbre 2.5 « Divisibilité par 2, 3, 4, 5, 9, 10, 11 »",
            "relation": "context",
            "note": "Les notions de multiple et de diviseur sont le préalable des critères de divisibilité (leçon 6).",
        },
    ],
    blocks={
        "fr": [
            P(
                "objectifs",
                "À la fin de cette leçon, tu sauras reconnaître un multiple d'un nombre, trouver les diviseurs d'un petit nombre et dire quand une division tombe juste.",
            ),
            P(
                "intro",
                "Un commerçant veut ranger 12 bouteilles en rangées égales, sans bouteille en trop. Il peut faire 1 rangée de 12, 2 rangées de 6, 3 rangées de 4, 4 rangées de 3, 6 rangées de 2 ou 12 rangées de 1. Les nombres 1, 2, 3, 4, 6 et 12 sont les diviseurs de 12.",
            ),
            H("multiples-titre", "Les multiples"),
            P(
                "multiples",
                "Les multiples d'un nombre sont les résultats de sa table de multiplication. Les multiples de 4 sont 4, 8, 12, 16, 20, et ainsi de suite : on n'arrive jamais au dernier.",
            ),
            EX(
                "exemple-multiples",
                "Reconnaître un multiple de 7",
                [
                    "On cherche si 28 est dans la table de 7.",
                    "7 × 4 = 28, donc 28 est un multiple de 7.",
                    "On dit aussi que 7 est un diviseur de 28 et que 28 est divisible par 7.",
                ],
            ),
            H("diviseurs-titre", "Les diviseurs"),
            P(
                "diviseurs",
                "Un nombre b est un diviseur d'un nombre a quand la division de a par b tombe juste, c'est-à-dire quand le reste est 0. On dit alors que a est divisible par b, ou que a est un multiple de b.",
            ),
            EX(
                "exemple-diviseurs",
                "Trouver tous les diviseurs de 12",
                [
                    "12 ÷ 1 = 12, reste 0 : 1 est un diviseur.",
                    "12 ÷ 2 = 6, reste 0 : 2 est un diviseur.",
                    "12 ÷ 3 = 4, reste 0 : 3 est un diviseur.",
                    "12 ÷ 4 = 3, reste 0 : 4 est un diviseur.",
                    "12 ÷ 5 = 2, reste 2 : 5 n'est pas un diviseur.",
                    "12 ÷ 6 = 2, reste 0 : 6 est un diviseur, et 12 ÷ 12 = 1 : 12 aussi.",
                    "Diviseurs de 12 : 1, 2, 3, 4, 6, 12",
                ],
            ),
            CO("astuce", "tip", "Pour trouver les diviseurs, cherche les couples de nombres dont le produit est le nombre : 12 = 1 × 12 = 2 × 6 = 3 × 4."),
            CO(
                "piege",
                "warning",
                "Attention : 1 et le nombre lui-même sont toujours des diviseurs. Un diviseur d'un nombre non nul n'est jamais plus grand que ce nombre.",
            ),
            CO(
                "retenir",
                "remember",
                "b est un diviseur de a, a est un multiple de b et a est divisible par b : trois façons de dire que la division de a par b a un reste égal à 0.",
            ),
        ],
        "ht": [
            P("objectifs", "Lè leson sa a fini, w ap konn rekonèt yon miltip yon nonb, jwenn divizè yon ti nonb, epi di ki lè yon divizyon egzat."),
            P(
                "intro",
                "Yon komèsan vle ranje 12 boutèy an ranje egal, san gen boutèy ki rete. Li ka fè 1 ranje 12, 2 ranje 6, 3 ranje 4, 4 ranje 3, 6 ranje 2 oswa 12 ranje 1. Nonb 1, 2, 3, 4, 6 ak 12 yo se divizè 12 yo.",
            ),
            H("multiples-titre", "Miltip yo"),
            P("multiples", "Miltip yon nonb se rezilta tab miltiplikasyon li. Miltip 4 yo se 4, 8, 12, 16, 20, epi konsa: nou pa janm rive nan dènye a."),
            EX(
                "exemple-multiples",
                "Rekonèt yon miltip 7",
                ["Nou chèche si 28 nan tab 7 la.", "7 × 4 = 28, donk 28 se yon miltip 7.", "Nou di tou 7 se yon divizè 28 epi 28 divizib pa 7."],
            ),
            H("diviseurs-titre", "Divizè yo"),
            P(
                "diviseurs",
                "Yon nonb b se yon divizè yon nonb a lè divizyon a pa b egzat, sa vle di lè rès la se 0. Nou di tou a divizib pa b, oswa a se yon miltip b.",
            ),
            EX(
                "exemple-diviseurs",
                "Jwenn tout divizè 12",
                [
                    "12 ÷ 1 = 12, rès 0: 1 se yon divizè.",
                    "12 ÷ 2 = 6, rès 0: 2 se yon divizè.",
                    "12 ÷ 3 = 4, rès 0: 3 se yon divizè.",
                    "12 ÷ 4 = 3, rès 0: 4 se yon divizè.",
                    "12 ÷ 5 = 2, rès 2: 5 pa yon divizè.",
                    "12 ÷ 6 = 2, rès 0: 6 se yon divizè, epi 12 ÷ 12 = 1: 12 tou.",
                    "Divizè 12 yo: 1, 2, 3, 4, 6, 12",
                ],
            ),
            CO("astuce", "tip", "Pou jwenn divizè yo, chèche koup nonb ki gen pwodui yo se nonb lan: 12 = 1 × 12 = 2 × 6 = 3 × 4."),
            CO("piege", "warning", "Atansyon: 1 ak nonb lan menm toujou se divizè. Yon divizè yon nonb ki pa zewo pa janm pi gwo pase nonb sa a."),
            CO("retenir", "remember", "b se yon divizè a, a se yon miltip b epi a divizib pa b: twa fason pou di divizyon a pa b gen yon rès ki egal ak 0."),
        ],
    },
    examples=[
        ExampleCheck("exemple-multiples", [{"expr": "7 * 4", "equals": 28, "must_appear": "7×4=28"}, {"expr": "28 % 7", "equals": 0, "must_appear": "28"}]),
        ExampleCheck(
            "exemple-diviseurs",
            [
                {"expr": "12 // 5", "equals": 2, "must_appear": "12÷5=2"},
                {"expr": "12 % 5", "equals": 2, "must_appear": "2"},
                {"expr": "[d for d in range(1, 13) if 12 % d == 0]", "equals": [1, 2, 3, 4, 6, 12], "must_appear": "1,2,3,4,6,12"},
            ],
        ),
    ],
    questions=[
        Q(
            "multiple-de-6",
            "truth",
            "c",
            prompt={"fr": "Lequel de ces nombres est un multiple de 6 ?", "ht": "Ki nan nonb sa yo ki yon miltip 6 ?"},
            choices=[
                C(expr="16 % 6 == 0", fr="16", ht="16"),
                C(expr="26 % 6 == 0", fr="26", ht="26"),
                C(expr="36 % 6 == 0", fr="36", ht="36"),
                C(expr="46 % 6 == 0", fr="46", ht="46"),
            ],
            explanation={
                "fr": "6 × 6 = 36, donc 36 est dans la table de 6. Les autres nombres ont un reste quand on les divise par 6.",
                "ht": "6 × 6 = 36, donk 36 nan tab 6 la. Lòt nonb yo gen yon rès lè nou divize yo pa 6.",
            },
        ),
        Q(
            "diviseurs-de-10",
            "truth",
            "a",
            prompt={"fr": "Quels sont tous les diviseurs de 10 ?", "ht": "Ki se tout divizè 10 yo ?"},
            choices=[
                C(expr="[d for d in range(1, 11) if 10 % d == 0] == [1, 2, 5, 10]", fr="1, 2, 5, 10", ht="1, 2, 5, 10"),
                C(expr="[d for d in range(1, 11) if 10 % d == 0] == [1, 2, 3, 5, 10]", fr="1, 2, 3, 5, 10", ht="1, 2, 3, 5, 10"),
                C(expr="[d for d in range(1, 11) if 10 % d == 0] == [2, 5, 10]", fr="2, 5, 10", ht="2, 5, 10"),
                C(expr="[d for d in range(1, 11) if 10 % d == 0] == [1, 5, 10]", fr="1, 5, 10", ht="1, 5, 10"),
            ],
            explanation={
                "fr": "10 ÷ 1 = 10, 10 ÷ 2 = 5, 10 ÷ 5 = 2 et 10 ÷ 10 = 1 tombent juste. 3 n'est pas un diviseur de 10 : 10 ÷ 3 = 3, reste 1.",
                "ht": "10 ÷ 1 = 10, 10 ÷ 2 = 5, 10 ÷ 5 = 2 ak 10 ÷ 10 = 1 egzat. 3 pa yon divizè 10: 10 ÷ 3 = 3, rès 1.",
            },
        ),
        Q(
            "divisible-par-8",
            "truth",
            "a",
            prompt={"fr": "Le nombre 24 est-il divisible par 8 ?", "ht": "Èske nonb 24 divizib pa 8 ?"},
            choices=[
                C(expr="24 % 8 == 0 and 8 * 3 == 24", fr="Oui, car 8 × 3 = 24", ht="Wi, paske 8 × 3 = 24"),
                C(expr="24 % 8 == 8", fr="Non, car il reste 8", ht="Non, paske li rete 8"),
                C(expr="24 % 8 != 0", fr="Non, car 24 est plus grand que 8", ht="Non, paske 24 pi gwo pase 8"),
                C(expr="24 + 8 == 32 and 24 % 8 != 0", fr="Oui, car 24 + 8 = 32", ht="Wi, paske 24 + 8 = 32"),
            ],
            explanation={
                "fr": "8 × 3 = 24, donc 24 ÷ 8 = 3 et le reste est 0 : 24 est divisible par 8.",
                "ht": "8 × 3 = 24, donk 24 ÷ 8 = 3 epi rès la se 0: 24 divizib pa 8.",
            },
        ),
        Q(
            "nombre-de-diviseurs-de-7",
            "value",
            "b",
            compute="len([d for d in range(1, 8) if 7 % d == 0])",
            prompt={"fr": "Combien de diviseurs le nombre 7 a-t-il ?", "ht": "Konbyen divizè nonb 7 genyen ?"},
            choices=[C(1), C(2), C(3), C(7)],
            explanation={"fr": "7 est seulement divisible par 1 et par 7 : il a 2 diviseurs.", "ht": "7 divizib sèlman pa 1 ak pa 7: li gen 2 divizè."},
        ),
        Q(
            "rangees-de-livres",
            "value",
            "c",
            compute="min([n for n in (2, 3, 4, 6) if 18 % n != 0])",
            prompt={
                "fr": "On veut ranger 18 livres en rangées égales, sans livre en trop. Parmi ces nombres de livres par rangée, lequel est impossible : 2, 3, 4 ou 6 ?",
                "ht": "Nou vle ranje 18 liv an ranje egal, san liv ki rete. Nan nonb liv pa ranje sa yo, ki yon sèl ki enposib: 2, 3, 4 oswa 6 ?",
            },
            choices=[C(2), C(3), C(4), C(6)],
            explanation={
                "fr": "18 ÷ 4 = 4, reste 2 : la division ne tombe pas juste. Avec 2, 3 ou 6 livres par rangée, il ne reste rien.",
                "ht": "18 ÷ 4 = 4, rès 2: divizyon an pa egzat. Ak 2, 3 oswa 6 liv pa ranje, pa gen anyen ki rete.",
            },
        ),
    ],
)
