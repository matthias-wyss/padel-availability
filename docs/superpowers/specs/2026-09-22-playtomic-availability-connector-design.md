# Design du connecteur de disponibilite Playtomic

## Statut

Design presente pour revue finale le 22 septembre 2026.

## Objectif

Ajouter le premier connecteur de disponibilite du projet en lecture seule. Il
collecte les creneaux publics de Playtomic pour les sites deja presents dans le
catalogue, les normalise et les conserve dans SQLite sous forme de snapshots.

Le connecteur ne reserve rien, ne demande aucun compte et ne construit pas
encore l'interface web.

## Perimetre

Le premier connecteur couvre les cinq locations dont le catalogue associe la
plateforme `Playtomic` :

- `padel-station`;
- `gva-palexpo`;
- `padel-parc-etoy`;
- `padel-parc-preverenges`;
- `vaudoise-arena`.

La fenetre demandee est de 14 jours par defaut. Le parametre de collecte
permet un autre horizon pour un run ou un site; aucune valeur globale de 14
jours n'est consideree comme une preuve sur la politique de reservation d'un
club.

Les creneaux sont conserves avec leur etat observe, y compris les creneaux
indisponibles. Un retour vide mais valide signifie seulement que le flux n'a
retourne aucun creneau pour la fenetre demandee; il ne signifie pas que le club
est ferme ou complet.

## Hors perimetre

- authentification, cookies, compte personnel ou session persistante;
- reservation, paiement, annulation ou mutation distante;
- contournement de CAPTCHA, limitation de debit ou protection anti-bot;
- automatisation de navigateur dans ce premier connecteur;
- scheduler, daemon ou execution periodique;
- interface web;
- connecteurs Bookinea, AIRPAD, Padel Connect et Padel One;
- tarifs, duree commerciale et regles d'acces supplementaires qui ne sont pas
  necessaires pour normaliser un creneau.

## Approche technique

Le connecteur consomme uniquement le flux JSON public utilise par les pages
Playtomic, via HTTP et la bibliotheque standard Python. L'URL exacte du flux
doit etre verifiee pendant l'implementation a partir de chaque URL de
reservation du catalogue; elle ne sera pas inventee ni supposee privee.

Si la page ou le flux exige une authentification, un cookie, un jeton prive,
un CAPTCHA ou une autre interaction non publique, le site produit un run
`unavailable` et aucune tentative de contournement n'est faite.

Les cinq sites sont collectes sequentiellement. Chaque site possede son
propre resultat; une erreur n'empeche pas les autres sites d'etre traites.
Les requetes ont un timeout borne et aucun retry automatique n'est ajoute dans
ce premier slice.

Les heures de jeu sont normalisees avec `Europe/Zurich` comme fuseau local et
stockees en UTC pour les instants persistants. Les timestamps de collecte sont
toujours des timestamps UTC finissant par `Z`.

## Modele de donnees

Le catalogue statique `locations` reste la source de l'identite physique. Le
connecteur ajoute deux tables SQLite:

### `availability_runs`

- `run_id` : identifiant unique du run pour un site;
- `location_id` : cle etrangere vers `locations`;
- `connector` : `playtomic`;
- `source_url` : URL publique utilisee;
- `window_start` et `window_end` : bornes de la fenetre en date locale;
- `horizon_days` : valeur effectivement demandee;
- `collected_at` : timestamp UTC;
- `status` : `success`, `error` ou `unavailable`;
- `error` : message public et borne, nullable.

Un run `success` est valide meme avec zero creneau. Les erreurs ne suppriment
jamais les runs precedents.

### `availability_slots`

- `run_id` : cle etrangere vers `availability_runs`;
- `location_id` : cle etrangere vers `locations`;
- `slot_key` : identifiant stable dans un run;
- `external_id` : identifiant Playtomic quand il existe;
- `court_label` : nom du court quand il est fourni;
- `starts_at` et `ends_at` : instants UTC normalises;
- `timezone` : `Europe/Zurich` pour l'affichage local;
- `status` : `available`, `unavailable` ou `unknown`.

La cle primaire logique est `(run_id, slot_key)`. Un slot dont l'etat ne peut
pas etre determine reste `unknown`; il n'est pas transforme en indisponible.

La lecture du dernier etat ne supprime pas l'historique : si le dernier run
est `error` ou `unavailable`, le dernier run `success` reste consultable et
est expose comme `stale` avec l'erreur du run courant.

## Flux CLI

La commande manuelle est:

```bash
uv run padel-availability collect-playtomic \
  --database var/catalog.sqlite3 \
  --days 14
```

`--location-id` limite la collecte a un site. La commande affiche un resume
deterministe par site, comprenant le statut, la fenetre, le nombre de
creneaux, le dernier succes et l'erreur eventuelle. Elle retourne `0` lorsque
chaque site selectionne a produit un resultat persiste (`success`, `error` ou
`unavailable`) et `2` pour une erreur d'arguments, de validation ou de base.

La collecte ne regenere pas encore `reports/inventory.md`; ce rapport reste le
rapport du catalogue statique. Un rapport de disponibilite et la webapp seront
des tranches ulterieures.

## Tests et verification

Les tests par defaut restent offline et deterministes:

- fixture JSON Playtomic avec creneaux disponibles et indisponibles;
- parsing des identifiants, courts, dates et etats;
- conversion Europe/Zurich vers UTC, y compris les horaires locaux;
- deduplication et identifiants de slots stables;
- fenetre par defaut de 14 jours et override `--days`;
- persistence d'un run et de ses slots dans une base temporaire;
- erreur d'un site sans interruption des autres;
- conservation du dernier snapshot apres un run en erreur;
- commande sans credentials, cookies, session ou appel reseau de test.

Un test live explicite pourra etre lance manuellement pour verifier la source
publique actuelle, mais il ne fera pas partie de `pytest` par defaut.

## Criteres d'acceptation

Le slice est termine lorsque:

1. les cinq locations Playtomic peuvent etre selectionnees depuis le catalogue;
2. `--days 14` est la valeur par defaut et un override est possible;
3. les creneaux observes sont persistants avec un etat et des timestamps
   normalises;
4. une source inaccessible produit un statut explicite sans effacer le
   dernier snapshot reussi;
5. un echec isole n'empeche pas les autres locations d'etre traitees;
6. les tests offline couvrent le parsing, la normalisation, SQLite et les
   erreurs;
7. aucune authentification, reservation, automatisation de navigateur,
   interface web ou execution planifiee n'est ajoutee.
