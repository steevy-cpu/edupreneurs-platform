from ..lib import CO, EX, C, ExampleCheck, H, Lesson, P, Q

LESSON = Lesson(
    slug="criteres-de-divisibilite",
    position=6,
    titles={"fr": "Les critères de divisibilité", "ht": "Kritè divizibilite yo"},
    objectives={
        "fr": [
            "Utiliser les critères de divisibilité par 2, 5 et 10 (dernier chiffre).",
            "Utiliser les critères de divisibilité par 3 et 9 (somme des chiffres) et par 4 (deux derniers chiffres).",
            "Vérifier une conclusion avec une division.",
        ],
        "ht": [
            "Sèvi ak kritè divizibilite pa 2, 5 ak 10 (dènye chif la).",
            "Sèvi ak kritè divizibilite pa 3 ak 9 (som chif yo) epi pa 4 (de dènye chif yo).",
            "Verifye yon konklizyon ak yon divizyon.",
        ],
    },
    refs=[
        {
            "source": "S1",
            "locator": "p. imprimée 38 (PDF p. 39), unité « Nombres et calculs », 7e année : « critères de divisibilité par 2, 3, 4, 5, 9, 10 »",
            "relation": "direct",
            "note": "Couvre exactement la liste 2, 3, 4, 5, 9, 10 de ce programme.",
        },
        {
            "source": "S2",
            "locator": "PDF p. 9 (janvier, semaine 3), Algèbre 2.5.1 « Appliquer les critères de divisibilité par : 2, 3, 4, 5, 9, 10, 11 »",
            "relation": "partial",
            "note": "Le critère de 11, présent seulement dans ce programme de 2019, n'est pas traité.",
        },
    ],
    blocks={
        "fr": [
            P(
                "objectifs",
                "À la fin de cette leçon, tu sauras utiliser les critères de divisibilité par 2, 3, 4, 5, 9 et 10 pour savoir, sans faire la division, si un nombre se partage sans reste.",
            ),
            P(
                "intro",
                "Une directrice a 135 cahiers. Peut-elle les répartir en 9 paquets égaux, sans cahier en trop ? On peut le savoir sans faire la division : il existe des critères de divisibilité.",
            ),
            H("criteres-titre", "Les critères de divisibilité"),
            P(
                "criteres-2-5-10",
                "Un nombre est divisible par 2 si son dernier chiffre est 0, 2, 4, 6 ou 8. Il est divisible par 5 si son dernier chiffre est 0 ou 5. Il est divisible par 10 si son dernier chiffre est 0.",
            ),
            P(
                "criteres-3-9",
                "Un nombre est divisible par 3 si la somme de ses chiffres est divisible par 3. Il est divisible par 9 si la somme de ses chiffres est divisible par 9.",
            ),
            P(
                "critere-4",
                "Un nombre est divisible par 4 si le nombre formé par ses deux derniers chiffres est divisible par 4, ou si ces deux chiffres sont 00.",
            ),
            EX(
                "exemple-612",
                "Étudier le nombre 612",
                [
                    "Dernier chiffre : 2, donc 612 est divisible par 2. Il n'est pas divisible par 5 ni par 10.",
                    "Somme des chiffres : 6 + 1 + 2 = 9. Comme 9 est divisible par 3 et par 9, 612 est divisible par 3 et par 9.",
                    "Deux derniers chiffres : 12. Comme 12 est divisible par 4, 612 est divisible par 4.",
                    "Vérification : 612 ÷ 9 = 68 et 612 ÷ 4 = 153.",
                ],
            ),
            EX(
                "exemple-745",
                "Étudier le nombre 745",
                [
                    "Dernier chiffre : 5, donc 745 est divisible par 5. Il n'est pas divisible par 2 ni par 10.",
                    "Somme des chiffres : 7 + 4 + 5 = 16. Comme 16 n'est pas divisible par 3, 745 n'est pas divisible par 3, ni par 9.",
                    "Deux derniers chiffres : 45. Comme 45 n'est pas divisible par 4, 745 n'est pas divisible par 4.",
                    "Vérification : 745 ÷ 5 = 149.",
                ],
            ),
            CO(
                "piege",
                "warning",
                "Attention : pour 3 et pour 9, on additionne tous les chiffres, pas seulement les derniers. Un nombre divisible par 3 n'est pas toujours divisible par 9 : 12 est divisible par 3, mais pas par 9.",
            ),
            CO(
                "retenir",
                "remember",
                "Dernier chiffre : critères de 2, 5 et 10. Deux derniers chiffres : critère de 4. Somme des chiffres : critères de 3 et de 9.",
            ),
        ],
        "ht": [
            P(
                "objectifs",
                "Lè leson sa a fini, w ap konn sèvi ak kritè divizibilite pa 2, 3, 4, 5, 9 ak 10 pou konnen, san fè divizyon an, si yon nonb ka pataje san gen rès.",
            ),
            P(
                "intro",
                "Yon direktris gen 135 kaye. Èske li ka separe yo an 9 pake egal, san kaye ki rete ? Nou ka konnen sa san fè divizyon an: gen kritè divizibilite.",
            ),
            H("criteres-titre", "Kritè divizibilite yo"),
            P(
                "criteres-2-5-10",
                "Yon nonb divizib pa 2 si dènye chif li se 0, 2, 4, 6 oswa 8. Li divizib pa 5 si dènye chif li se 0 oswa 5. Li divizib pa 10 si dènye chif li se 0.",
            ),
            P("criteres-3-9", "Yon nonb divizib pa 3 si som chif li yo divizib pa 3. Li divizib pa 9 si som chif li yo divizib pa 9."),
            P("critere-4", "Yon nonb divizib pa 4 si nonb ki fòme ak de dènye chif li yo divizib pa 4, oswa si de chif sa yo se 00."),
            EX(
                "exemple-612",
                "Etidye nonb 612",
                [
                    "Dènye chif: 2, donk 612 divizib pa 2. Li pa divizib pa 5 ni pa 10.",
                    "Som chif yo: 6 + 1 + 2 = 9. Kòm 9 divizib pa 3 ak pa 9, 612 divizib pa 3 ak pa 9.",
                    "De dènye chif yo: 12. Kòm 12 divizib pa 4, 612 divizib pa 4.",
                    "Verifikasyon: 612 ÷ 9 = 68 ak 612 ÷ 4 = 153.",
                ],
            ),
            EX(
                "exemple-745",
                "Etidye nonb 745",
                [
                    "Dènye chif: 5, donk 745 divizib pa 5. Li pa divizib pa 2 ni pa 10.",
                    "Som chif yo: 7 + 4 + 5 = 16. Kòm 16 pa divizib pa 3, 745 pa divizib pa 3, ni pa 9.",
                    "De dènye chif yo: 45. Kòm 45 pa divizib pa 4, 745 pa divizib pa 4.",
                    "Verifikasyon: 745 ÷ 5 = 149.",
                ],
            ),
            CO(
                "piege",
                "warning",
                "Atansyon: pou 3 ak pou 9, nou adisyone tout chif yo, pa sèlman dènye yo. Yon nonb ki divizib pa 3 pa toujou divizib pa 9: 12 divizib pa 3, men pa pa 9.",
            ),
            CO("retenir", "remember", "Dènye chif: kritè 2, 5 ak 10. De dènye chif: kritè 4. Som chif yo: kritè 3 ak 9."),
        ],
    },
    examples=[
        ExampleCheck(
            "exemple-612",
            [
                {"expr": "612 % 2 == 0 and 612 % 5 != 0 and 612 % 10 != 0", "equals": True, "must_appear": "612"},
                {"expr": "6 + 1 + 2", "equals": 9, "must_appear": "6+1+2=9"},
                {"expr": "612 % 3 == 0 and 612 % 9 == 0 and 12 % 4 == 0 and 612 % 4 == 0", "equals": True, "must_appear": "12"},
                {"expr": "612 // 9", "equals": 68, "must_appear": "612÷9=68"},
                {"expr": "612 // 4", "equals": 153, "must_appear": "612÷4=153"},
            ],
        ),
        ExampleCheck(
            "exemple-745",
            [
                {"expr": "745 % 5 == 0 and 745 % 2 != 0 and 745 % 10 != 0", "equals": True, "must_appear": "745"},
                {"expr": "7 + 4 + 5", "equals": 16, "must_appear": "7+4+5=16"},
                {"expr": "16 % 3 != 0 and 745 % 3 != 0 and 745 % 9 != 0", "equals": True, "must_appear": "16"},
                {"expr": "45 % 4 != 0 and 745 % 4 != 0", "equals": True, "must_appear": "45"},
                {"expr": "745 // 5", "equals": 149, "must_appear": "745÷5=149"},
            ],
        ),
    ],
    questions=[
        Q(
            "divisible-par-5-pas-10",
            "truth",
            "b",
            prompt={"fr": "Lequel de ces nombres est divisible par 5, mais pas par 10 ?", "ht": "Ki nan nonb sa yo ki divizib pa 5, men pa pa 10 ?"},
            choices=[
                C(expr="3210 % 5 == 0 and 3210 % 10 != 0", fr="3 210", ht="3 210"),
                C(expr="3215 % 5 == 0 and 3215 % 10 != 0", fr="3 215", ht="3 215"),
                C(expr="3216 % 5 == 0 and 3216 % 10 != 0", fr="3 216", ht="3 216"),
                C(expr="3217 % 5 == 0 and 3217 % 10 != 0", fr="3 217", ht="3 217"),
            ],
            explanation={
                "fr": "Le dernier chiffre de 3 215 est 5 : il est divisible par 5. Il ne finit pas par 0, donc il n'est pas divisible par 10. Le nombre 3 210 finit par 0 : il est divisible par 10.",
                "ht": "Dènye chif 3 215 la se 5: li divizib pa 5. Li pa fini ak 0, donk li pa divizib pa 10. Nonb 3 210 la fini ak 0: li divizib pa 10.",
            },
        ),
        Q(
            "divisible-par-3",
            "truth",
            "c",
            prompt={"fr": "Lequel de ces nombres est divisible par 3 ?", "ht": "Ki nan nonb sa yo ki divizib pa 3 ?"},
            choices=[
                C(expr="125 % 3 == 0", fr="125", ht="125"),
                C(expr="214 % 3 == 0", fr="214", ht="214"),
                C(expr="351 % 3 == 0", fr="351", ht="351"),
                C(expr="407 % 3 == 0", fr="407", ht="407"),
            ],
            explanation={
                "fr": "3 + 5 + 1 = 9 et 9 est divisible par 3. Pour les autres nombres, la somme des chiffres est 8, 7 et 11 : aucune n'est divisible par 3.",
                "ht": "3 + 5 + 1 = 9 epi 9 divizib pa 3. Pou lòt nonb yo, som chif yo se 8, 7 ak 11: pa gen youn ki divizib pa 3.",
            },
        ),
        Q(
            "divisible-par-9",
            "truth",
            "c",
            prompt={"fr": "Lequel de ces nombres est divisible par 9 ?", "ht": "Ki nan nonb sa yo ki divizib pa 9 ?"},
            choices=[
                C(expr="4321 % 9 == 0", fr="4 321", ht="4 321"),
                C(expr="4325 % 9 == 0", fr="4 325", ht="4 325"),
                C(expr="4329 % 9 == 0", fr="4 329", ht="4 329"),
                C(expr="4328 % 9 == 0", fr="4 328", ht="4 328"),
            ],
            explanation={
                "fr": "4 + 3 + 2 + 9 = 18 et 18 est divisible par 9. Les autres sommes sont 10, 14 et 17 : elles ne sont pas divisibles par 9.",
                "ht": "4 + 3 + 2 + 9 = 18 epi 18 divizib pa 9. Lòt som yo se 10, 14 ak 17: yo pa divizib pa 9.",
            },
        ),
        Q(
            "affirmation-vraie",
            "truth",
            "c",
            prompt={"fr": "Laquelle de ces affirmations est vraie ?", "ht": "Ki nan afimasyon sa yo ki vre ?"},
            choices=[
                C(expr="1236 % 5 == 0", fr="1 236 est divisible par 5", ht="1 236 divizib pa 5"),
                C(expr="1236 % 9 == 0", fr="1 236 est divisible par 9", ht="1 236 divizib pa 9"),
                C(
                    expr="1236 % 2 == 0 and 1236 % 3 == 0 and 1236 % 4 == 0",
                    fr="1 236 est divisible par 2, par 3 et par 4",
                    ht="1 236 divizib pa 2, pa 3 ak pa 4",
                ),
                C(expr="1236 % 10 == 0", fr="1 236 est divisible par 10", ht="1 236 divizib pa 10"),
            ],
            explanation={
                "fr": "Le dernier chiffre est 6 : divisible par 2. 1 + 2 + 3 + 6 = 12 : divisible par 3, mais pas par 9. 36 est divisible par 4. Le nombre ne finit ni par 0 ni par 5.",
                "ht": "Dènye chif la se 6: divizib pa 2. 1 + 2 + 3 + 6 = 12: divizib pa 3, men pa pa 9. 36 divizib pa 4. Nonb lan pa fini ni ak 0 ni ak 5.",
            },
        ),
        Q(
            "cahiers-en-paquets",
            "truth",
            "a",
            prompt={
                "fr": "Une directrice a 135 cahiers. Peut-elle les répartir en 9 paquets égaux, sans cahier en trop ?",
                "ht": "Yon direktris gen 135 kaye. Èske li ka separe yo an 9 pake egal, san kaye ki rete ?",
            },
            choices=[
                C(
                    expr="135 % 9 == 0 and (1 + 3 + 5) % 9 == 0",
                    fr="Oui, car la somme des chiffres 1 + 3 + 5 = 9 est divisible par 9",
                    ht="Wi, paske som chif yo 1 + 3 + 5 = 9 divizib pa 9",
                ),
                C(expr="135 % 9 != 0", fr="Non, car 135 est un nombre impair", ht="Non, paske 135 se yon nonb enpè"),
                C(expr="135 % 9 != 0 and 135 % 10 != 0", fr="Non, car 135 ne finit pas par 0", ht="Non, paske 135 pa fini ak 0"),
                C(expr="135 % 2 == 0", fr="Oui, car 135 est divisible par 2", ht="Wi, paske 135 divizib pa 2"),
            ],
            explanation={
                "fr": "1 + 3 + 5 = 9, donc 135 est divisible par 9 : 135 ÷ 9 = 15. Chaque paquet contient 15 cahiers.",
                "ht": "1 + 3 + 5 = 9, donk 135 divizib pa 9: 135 ÷ 9 = 15. Chak pake gen 15 kaye.",
            },
        ),
    ],
)
