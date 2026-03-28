CREATE TABLE "Entreprise" (
  "id_ent" int PRIMARY KEY,
  "nom" varchar,
  "adresse" varchar,
  "tel" varchar
);

CREATE TABLE "Utilisateur" (
  "id_user" int PRIMARY KEY,
  "username" varchar,
  "password" varchar,
  "role" varchar
);

CREATE TABLE "Client" (
  "code_cl" int PRIMARY KEY,
  "designation" varchar,
  "tel" varchar
);

CREATE TABLE "Fournisseur" (
  "num_f" int PRIMARY KEY,
  "designation" varchar,
  "tel" varchar
);

CREATE TABLE "Produit" (
  "code_p" int PRIMARY KEY,
  "designation" varchar,
  "qte_stock" int,
  "stock_alerte" int
);

CREATE TABLE "Bon_Entree" (
  "num_e" int PRIMARY KEY,
  "date_e" datetime,
  "id_fourn" int,
  "id_user" int
);

CREATE TABLE "Ligne_Entree" (
  "id_le" int PRIMARY KEY,
  "num_e" int,
  "code_p" int,
  "qte_e" int
);

CREATE TABLE "Bon_Sortie" (
  "num_s" int PRIMARY KEY,
  "date_s" datetime,
  "code_cl" int,
  "id_user" int
);

CREATE TABLE "Ligne_Sortie" (
  "id_ls" int PRIMARY KEY,
  "num_s" int,
  "code_p" int,
  "qte_s" int
);

ALTER TABLE "Bon_Entree" ADD FOREIGN KEY ("id_user") REFERENCES "Utilisateur" ("id_user") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "Bon_Sortie" ADD FOREIGN KEY ("id_user") REFERENCES "Utilisateur" ("id_user") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "Bon_Entree" ADD FOREIGN KEY ("id_fourn") REFERENCES "Fournisseur" ("num_f") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "Ligne_Entree" ADD FOREIGN KEY ("num_e") REFERENCES "Bon_Entree" ("num_e") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "Ligne_Entree" ADD FOREIGN KEY ("code_p") REFERENCES "Produit" ("code_p") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "Bon_Sortie" ADD FOREIGN KEY ("code_cl") REFERENCES "Client" ("code_cl") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "Ligne_Sortie" ADD FOREIGN KEY ("num_s") REFERENCES "Bon_Sortie" ("num_s") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "Ligne_Sortie" ADD FOREIGN KEY ("code_p") REFERENCES "Produit" ("code_p") DEFERRABLE INITIALLY IMMEDIATE;
