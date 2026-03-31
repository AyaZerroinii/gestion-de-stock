CREATE TABLE "Entreprise" (
  "id_ent" SERIAL PRIMARY KEY,
  "nom" VARCHAR(255),
  "adresse" VARCHAR(255),
  "tel" VARCHAR(20)
);

CREATE TABLE "Utilisateur" (
  "id_user" SERIAL PRIMARY KEY,
  "username" VARCHAR(255),
  "password" VARCHAR(255),
  "role" VARCHAR(50)
);

CREATE TABLE "Client" (
  "code_cl" SERIAL PRIMARY KEY,
  "designation" VARCHAR(255),
  "tel" VARCHAR(20)
);

CREATE TABLE "Fournisseur" (
  "num_f" SERIAL PRIMARY KEY,
  "designation" VARCHAR(255),
  "tel" VARCHAR(20)
);

CREATE TABLE "Produit" (
  "code_p" SERIAL PRIMARY KEY,
  "designation" VARCHAR(255),
  "qte_stock" INT,
  "stock_alerte" INT
);

CREATE TABLE "Bon_Entree" (
  "num_e" SERIAL PRIMARY KEY,
  "date_e" TIMESTAMP,
  "id_fourn" INT,
  "id_user" INT
);

CREATE TABLE "Ligne_Entree" (
  "id_le" SERIAL PRIMARY KEY,
  "num_e" INT,
  "code_p" INT,
  "qte_e" INT
);

CREATE TABLE "Bon_Sortie" (
  "num_s" SERIAL PRIMARY KEY,
  "date_s" TIMESTAMP,
  "code_cl" INT,
  "id_user" INT
);

CREATE TABLE "Ligne_Sortie" (
  "id_ls" SERIAL PRIMARY KEY,
  "num_s" INT,
  "code_p" INT,
  "qte_s" INT
);

-- FOREIGN KEYS
ALTER TABLE "Bon_Entree" 
    ADD CONSTRAINT fk_bon_ent_user FOREIGN KEY ("id_user") REFERENCES "Utilisateur" ("id_user");

ALTER TABLE "Bon_Sortie" 
    ADD CONSTRAINT fk_bon_sortie_user FOREIGN KEY ("id_user") REFERENCES "Utilisateur" ("id_user");

ALTER TABLE "Bon_Entree" 
    ADD CONSTRAINT fk_bon_ent_fourn FOREIGN KEY ("id_fourn") REFERENCES "Fournisseur" ("num_f");

ALTER TABLE "Ligne_Entree" 
    ADD CONSTRAINT fk_ligne_ent_bon FOREIGN KEY ("num_e") REFERENCES "Bon_Entree" ("num_e");

ALTER TABLE "Ligne_Entree" 
    ADD CONSTRAINT fk_ligne_ent_prod FOREIGN KEY ("code_p") REFERENCES "Produit" ("code_p");

ALTER TABLE "Bon_Sortie" 
    ADD CONSTRAINT fk_bon_sortie_client FOREIGN KEY ("code_cl") REFERENCES "Client" ("code_cl");

ALTER TABLE "Ligne_Sortie" 
    ADD CONSTRAINT fk_ligne_sortie_bon FOREIGN KEY ("num_s") REFERENCES "Bon_Sortie" ("num_s");

ALTER TABLE "Ligne_Sortie" 
    ADD CONSTRAINT fk_ligne_sortie_prod FOREIGN KEY ("code_p") REFERENCES "Produit" ("code_p");