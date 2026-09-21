# Padel Availability - Design de l'inventaire et de l'agregateur

## Statut

Design approuve le 21 septembre 2026.

## Objectif

Construire un site web mobile-first qui aide a trouver des terrains de padel disponibles entre Geneve, La Cote, Morges, Lausanne et les communes voisines.

La premiere livraison constitue un catalogue fiable de tous les sites candidats fournis par l'utilisateur. Elle conserve les sources et les incertitudes afin de servir de base aux futurs connecteurs de disponibilite et a la webapp.

Le projet est independant du depot `cairn` et vit dans `projects/padel-availability`.

## Perimetre de la premiere livraison

La livraison d'inventaire doit :

- reprendre chaque entree de la liste initiale sans perdre son nom original ;
- representer un site physique canonique par fiche ;
- detecter et documenter les doublons, alias et changements de nom ;
- confirmer les caracteristiques a partir de sources publiques ;
- conserver les sites prives, universitaires, saisonniers ou incertains avec leur restriction ;
- fournir le site officiel et le lien de reservation lorsqu'ils sont disponibles ;
- identifier la plateforme de reservation lorsqu'elle peut etre determinee ;
- indiquer si un compte ou une adhesion semble necessaire ;
- documenter terrains, couverture, acces, prix, durees, vestiaires et location de raquettes lorsqu'ils sont publies ;
- enregistrer la source, la date de verification, la preuve et le niveau de confiance de chaque information importante ;
- produire une base SQLite et un rapport de verification exploitable par la suite.

Les disponibilites horaires en temps reel ou differe ne font pas partie de cette premiere livraison. Le modele de donnees reserve toutefois leur place pour eviter une migration conceptuelle lors de l'ajout des connecteurs.

## Hors perimetre

- reservation ou paiement automatique ;
- contournement ou resolution automatique de CAPTCHA ;
- contournement d'une authentification, d'une limitation technique ou des conditions d'utilisation d'un site ;
- collecte avec des identifiants personnels pendant l'inventaire ;
- compte utilisateur, favoris et notifications ;
- calcul de distance depuis un point non defini ;
- carte de trajet et estimation de transport ;
- scraping de disponibilites avant l'audit des plateformes.

## Principes de donnees

### Identite canonique

Une fiche correspond a un site physique, pas a une marque ni a une plateforme. Les quatre sites AIRPAD sont donc quatre fiches distinctes. Une fiche conserve les alias connus afin qu'une recherche par ancien nom reste possible.

Une fusion n'est automatique que si le nom, la commune, l'adresse ou les coordonnees et les sources convergent. Une ressemblance de nom seule ne suffit pas. Un conflit non resolu conserve deux candidats et le statut `a_verifier`.

### Valeurs inconnues

Une information non trouvee est `inconnu`, jamais `non`. Les valeurs booleennes concernant l'acces, l'adhesion, les vestiaires et les raquettes sont donc tri-etat : `oui`, `non`, `inconnu`.

Les informations contradictoires portent une note explicite avec les sources en conflit. Elles ne sont pas tranchees par une supposition.

### Provenance

Les sources officielles du club, de l'exploitant ou de la commune sont prioritaires. Les associations cantonales, plateformes de reservation et sources regionales servent de corroboration ou de decouverte. Chaque source enregistree contient au minimum :

- URL ;
- type de source ;
- titre ou description courte ;
- date de verification ;
- faits soutenus ou contredits ;
- note de preuve ;
- niveau de confiance.

Une page qui ne confirme qu'une partie de la fiche ne sera pas presentee comme la preuve de toute la fiche.

## Modele de donnees initial

SQLite est la source locale de lecture pour l'inventaire. Les tables minimales sont :

### `locations`

Une ligne par site physique :

- identifiant stable ;
- nom canonique, marque et alias ;
- commune, adresse et coordonnees si confirmees ;
- nombre de terrains et detail des terrains si connu ;
- statut de couverture : `indoor`, `outdoor`, `partiellement_couvert`, `saisonnier`, `inconnu` ;
- acces : `public`, `membres`, `universitaire`, `conditions`, `inconnu` ;
- adhesion necessaire en tri-etat ;
- reservation publique en tri-etat ;
- location de raquettes en tri-etat et remarque ;
- vestiaires en tri-etat et remarque ;
- site officiel et lien de reservation ;
- plateforme de reservation et exigence de compte ;
- statut de verification : `confirme`, `probable`, `a_verifier`, `non_confirme`, `ferme` ;
- dates de premiere et derniere verification ;
- remarque de synthese.

### `location_sources`

Association entre un site et une source, avec la nature de la relation et la preuve textuelle courte. Cette table permet de garder plusieurs sources sans ecraser l'historique.

### `candidate_entries`

Entrees telles que fournies dans la liste initiale, liees a une fiche canonique lorsqu'une correspondance est confirmee. Elles permettent de montrer les doublons, alias et candidats non resolus.

### `verification_runs`

Execution de verification avec date, zone couverte, nombre de fiches examinees, erreurs et resume. Une nouvelle verification ajoute une execution ; elle ne remplace pas silencieusement la precedente.

### Extension future `availability_slots`

La collecte de disponibilites ajoutera au minimum : site, terrain, debut UTC ou heure locale source, duree, prix, devise, statut, URL directe, connecteur, `observed_at`, et statut de fraicheur. Les heures locales des clubs seront preservees a la frontiere puis normalisees pour les recherches.

## Flux de verification

1. Importer la liste initiale dans `candidate_entries`.
2. Rechercher le site officiel de chaque candidat.
3. Trouver le lien de reservation et identifier la plateforme sans se connecter.
4. Comparer nom, commune, adresse, coordonnees, nombre de terrains et sources pour les doublons.
5. Enregistrer les faits confirmes et les faits inconnus.
6. Comparer les contradictions et les signaler dans les notes.
7. Classer chaque candidat et chaque site canonique.
8. Generer le rapport : confirmes, fusionnes, incertains, fermes, incomplets et prets pour un futur connecteur.

Le rapport doit distinguer :

- site existe mais disponibilite non accessible ;
- site existe et reservation publique identifiee ;
- site existe mais reservation reservee aux membres ou soumise a conditions ;
- existence non confirmee ;
- doublon ou alias d'un autre site.

## Connecteurs futurs

L'audit regroupera les clubs par plateforme. Un connecteur sera partage par plusieurs clubs quand le fonctionnement est commun ; une configuration specifique au club portera les URL, terrains, regles et limites locales. Un connecteur dedie ne sera cree que si aucune plateforme partagee ne convient.

Chaque connecteur devra produire des creneaux normalises et declarer :

- sa couverture de dates et de terrains ;
- sa derniere collecte reussie ;
- les donnees manquantes ;
- les erreurs d'authentification, CAPTCHA, changement de page ou limitation ;
- si le resultat est complet ou partiel.

Une collecte partielle ne sera pas interpretee comme une absence de disponibilite. Les resultats anciens seront marques perimes. Les collectes utiliseront cache, limites de requetes et liens officiels. Aucun connecteur ne devra declencher une reservation ou un paiement.

## Webapp future

La webapp lira les donnees locales et restera utilisable lorsque des sites externes sont indisponibles. Elle comportera :

- recherche par date ou periode ;
- filtres zone, site, indoor/outdoor, duree et prix ;
- resultats groupes par jour et site ;
- heure, duree, prix, terrain et fraicheur visibles ;
- indication explicite des restrictions et de l'incertitude ;
- bouton de redirection vers la reservation officielle ;
- annuaire et fiche detaillee pour les sites sans connecteur.

Le premier frontend sera du HTML/CSS/JavaScript mobile-first, sans framework lourd. Un backend Python avec SQLite servira le catalogue et les resultats normalises.

## Erreurs, securite et secrets

Les erreurs de source sont conservees dans le rapport de verification et ne rendent pas toute la base inutilisable. Les champs sans preuve restent inconnus. Les identifiants, cookies et sessions ne sont jamais ecrits dans la base de catalogue, les fixtures, les journaux, le depot ou les rapports.

Les comptes dedies et secrets ne seront envisages qu'apres l'inventaire, pour les plateformes dont l'acces est autorise et necessaire. Ils seront fournis par l'environnement local ou un mecanisme de secrets, jamais par le chat.

## Verification et tests

La suite locale doit rester hors ligne par defaut et couvrir :

- import de la liste initiale ;
- normalisation des noms et detection des doublons ;
- fusion conservatrice des sites ;
- tri-etat et validation des statuts ;
- conservation des sources et dates de verification ;
- generation d'un rapport stable ;
- import/export SQLite ;
- normalisation de fixtures de disponibilite pour les futurs connecteurs ;
- marquage des donnees incompletes et perimees.

Les appels web reels seront separes des tests par des fixtures sauvegardees et des commandes explicites. Les changements de structure d'une plateforme devront echouer visiblement, pas produire silencieusement des disponibilites fausses.

## Decisions differees

- choix precis du framework HTTP et du mode de deploiement ;
- point de depart pour les distances ;
- calendrier de rafraichissement par plateforme ;
- comptes et secrets necessaires par plateforme ;
- notifications et favoris ;
- couverture des plateformes qui refusent toute collecte automatisee.

Ces decisions seront prises apres l'inventaire et l'audit des reservations, sur des faits observes plutot que sur des suppositions.
