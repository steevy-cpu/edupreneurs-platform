# Guide de relecture — pilote de mathématiques 7e AF

*(Pour un enseignant de mathématiques et un locuteur natif du créole haïtien. Aucune connaissance informatique n'est nécessaire.)*

## À quoi sert ce dossier ?

Edupreneurs prépare des leçons pour téléphones. Ce **pilote** contient **6 leçons** sur les nombres entiers naturels pour la **7e année fondamentale**,
chacune avec 5 exercices à choix multiple, en **français** et en **créole haïtien**.

**Tout est un brouillon.** Rien n'a été relu par un enseignant ni par un locuteur natif. Le choix de la 7e AF en mathématiques est lui-même
une *proposition*, pas une décision du propriétaire du projet. Ces textes ont été écrits avec l'aide d'une IA : ils peuvent contenir des erreurs,
des maladresses ou un créole peu naturel. **Votre rôle est de les juger sévèrement.**

## Ce que nous vous demandons

Pour chaque leçon (une feuille par leçon dans ce dossier) :

1. Lire le texte français, bloc par bloc, et noter pour chaque bloc **OK / Corriger / Rejeter**, avec la correction.
2. Lire les 5 exercices : la **réponse attendue** est-elle bien la seule bonne ? L'explication est-elle juste ? La question est-elle claire pour un élève de 7e année ?
3. Faire la même chose pour le **créole** (un locuteur natif ; idéalement aussi un enseignant).
4. Donner une décision par langue : **Approuver**, **Approuver avec corrections** ou **Rejeter**, et signer (nom, rôle, date).

Vous pouvez écrire sur la feuille imprimée, dans le fichier, ou remplir `decisions.template.csv` (un tableau avec une ligne par leçon, bloc et exercice, que
vous pouvez ouvrir dans un tableur).

## Ce que « approuvé » veut dire

Une langue d'une leçon n'est « approuvée » que si **deux personnes** l'ont signée : un **enseignant de mathématiques qualifié** et un **locuteur natif de cette langue**.
Aucune leçon n'a ce statut aujourd'hui. Les accords de principe, les « ça a l'air bien » ou la signature d'une seule personne ne suffisent pas.

## Les questions de programme (à ne pas ignorer)

Le dossier `docs/content-02a/01-source-register.md` explique ce qui a pu être vérifié sur les programmes officiels du MENFP et ce qui reste **incertain** :
deux documents officiels existent (un programme de 2024 et un programme à compétences minimales de 2019) et ils ne placent pas tous les sujets dans la même année.
Les leçons ne reprennent que ce que les deux documents ont en commun. **Dites-nous** si, selon vous, un sujet est mal placé en 7e année ou manque.

## Ce que les outils ont déjà contrôlé (et ce qu'ils ne peuvent pas contrôler)

Déjà contrôlé automatiquement : format des fichiers ; les égalités et comparaisons chiffrées écrites avec les symboles + − × ÷ = ≠ < > ≤ ≥ dans les textes, les énoncés
et les explications (calcul exact, sens des opérations respecté) ; chaque réponse attendue (recalculée) ; une seule bonne réponse par exercice ;
mêmes nombres en français et en créole ; absence de caractères parasites et de balisage ; tailles.

**Ce que l'outil n'interprète pas, volontairement** : les calculs avec des unités de mesure (`8 km = 8 000 m`), les décompositions en unités nommées
(`3 480 = 3 milliers + 4 centaines …`), les formules écrites avec des lettres, et toute notation qu'il ne sait pas lire (fraction écrite `1/2`, virgule décimale, puissance,
signe moins du clavier). Une notation non lisible dans une relation fait **échouer** la validation ; une relation laissée de côté est **listée** dans la feuille de la leçon
(rubrique « Calculs ») : c'est à vous de la vérifier. Aucun message de l'outil ne doit être lu comme « tous les calculs sont justes ».

**Non contrôlable par une machine** : la qualité pédagogique, la justesse du vocabulaire, le naturel du créole, l'adéquation au programme, la clarté pour un élève.
C'est précisément votre travail.

## Que faire de vos décisions ?

Renvoyez les feuilles (ou le CSV) à l'équipe Edupreneurs. Elle corrigera les textes, puis enregistrera les approbations (nom, rôle, date, référence du document signé)
dans le descripteur du pilote. Voir `docs/content-02a/06-path-to-content-02b.md`.

## Contenu du dossier

- `lesson-01-…` à `lesson-06-…` : une feuille de relecture par leçon (texte, exercices, tableaux de décision).
- `answer-key-overview.md` : toutes les réponses attendues sur une page.
- `decisions.template.csv` : tableau de décisions vide.
