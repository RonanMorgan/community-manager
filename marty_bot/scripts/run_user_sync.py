import logging
import os
import sys

# Ajoute le répertoire racine du projet au PYTHONPATH pour permettre les imports relatifs.
# Utile si le script est exécuté par cron où PYTHONPATH n'est pas toujours configuré.
current_script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_script_dir)  # marty_bot/
# Les imports comme `from libraries...` nécessitent que `marty_bot/` soit dans sys.path.
sys.path.insert(0, project_root)

try:
    from clients.authentik_client import AuthentikClient
    from dotenv import load_dotenv
    from libraries.brevo_user_sync import sync_authentik_users_to_brevo_list
    from libraries.user_management import remove_inactive_users
except ImportError as e:
    logging.basicConfig(level=logging.ERROR)
    logging.error(
        f"Erreur d'importation : {e}. Vérifiez PYTHONPATH ou exécutez depuis la racine.\n"
        f"PYTHONPATH actuel: {sys.path}"
    )
    sys.exit(1)


if __name__ == "__main__":
    # Charger .env depuis la racine du projet (marty_bot/.env)
    dotenv_path = os.path.join(project_root, ".env")

    # Configuration temporaire du logger pour les messages initiaux
    temp_logger = logging.getLogger("run_user_sync_setup")
    temp_handler = logging.StreamHandler(sys.stdout)
    temp_formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    temp_handler.setFormatter(temp_formatter)
    temp_logger.addHandler(temp_handler)
    temp_logger.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())

    if os.path.exists(dotenv_path):
        load_dotenv(dotenv_path=dotenv_path)
        temp_logger.info(f"Variables d'environnement chargées depuis {dotenv_path}")
    else:
        temp_logger.info(
            f"Fichier .env non trouvé à {dotenv_path}. "
            "Les variables d'environnement doivent être définies autrement."
        )

    # Configurer le logging pour le script
    log_dir = os.path.join(project_root, "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_file_path = os.path.join(log_dir, "user_sync.log")

    # Get root logger and remove existing handlers to avoid duplicate messages
    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    for handler in temp_logger.handlers[:]:
        temp_logger.removeHandler(handler)
    temp_logger.propagate = False

    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(module)s - %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_file_path),
        ],
    )

    logging.info("Démarrage du script de synchronisation des utilisateurs.")
    try:
        AUTHENTIK_URL = os.getenv("AUTHENTIK_URL")
        AUTHENTIK_TOKEN = os.getenv("AUTHENTIK_TOKEN")
        if not all([AUTHENTIK_URL, AUTHENTIK_TOKEN]):
            logging.error("Missing required environment variables for Authentik: AUTHENTIK_URL, AUTHENTIK_TOKEN")
            sys.exit(1)

        auth_client = AuthentikClient(base_url=AUTHENTIK_URL, token=AUTHENTIK_TOKEN)
        authentik_users = auth_client.get_all_users_data()

        if authentik_users is not None:
            sync_authentik_users_to_brevo_list(authentik_users)
            remove_inactive_users(["outline", "nocodb", "mattermost", "vaultwarden"], authentik_users)
        else:
            logging.error("Could not fetch Authentik users. Skipping sync.")

        logging.info("Script de synchronisation des utilisateurs terminé avec succès.")
    except Exception as e:
        logging.error(
            f"Une erreur s'est produite pendant l'exécution du script de synchronisation : {e}",
            exc_info=True,
        )
        sys.exit(1)
    sys.exit(0)
