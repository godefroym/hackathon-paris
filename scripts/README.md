# /scripts 📜

Scripts utilitaires pour la configuration de l'infrastructure de base de données.

## 📄 Contenu

*   `setup-*.sh` : Scripts Shell pour configurer PostgreSQL, MySQL ou Cassandra pour Temporal.
*   `mock_fact_check_receiver.py` : Serveur HTTP de test simulant un récepteur de résultats de fact-checking.

## ⚠️ Notes

Ces scripts sont principalement utilisés par `docker-compose.yml` lors de l'initialisation des services.
