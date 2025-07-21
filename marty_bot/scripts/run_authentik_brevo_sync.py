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
    from libraries.authentik_brevo_sync import sync_authentik_users_to_brevo_list
    from dotenv import load_dotenv
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
    temp_logger = logging.getLogger("run_authentik_brevo_sync_setup")
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
    # Vous pouvez ajuster le niveau de log et le format selon vos besoins.
    # Par exemple, logger dans un fichier spécifique pour les crons.
    log_dir = os.path.join(project_root, "logs")
    os.makedirs(log_dir, exist_ok=True)  # Crée le dossier logs s'il n'existe pas
    log_file_path = os.path.join(log_dir, "authentik_brevo_sync.log")

    # Get root logger and remove existing handlers to avoid duplicate messages if script is re-run in same env
    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    # Also remove handlers from our temp_logger if we don't want its messages via root
    for handler in temp_logger.handlers[:]:
        temp_logger.removeHandler(handler)
    temp_logger.propagate = False

    logging.basicConfig(
        level=os.getenv(
            "LOG_LEVEL", "INFO"
        ).upper(),  # Default INFO, peut être changé par env var
        format="%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(module)s - %(message)s",
        handlers=[
            logging.StreamHandler(
                sys.stdout
            ),  # Log vers stdout (visible dans les logs cron)
            logging.FileHandler(log_file_path),  # Log vers un fichier
        ],
    )

    logging.info("Démarrage du script de synchronisation Authentik vers Brevo.")
    try:
        sync_authentik_users_to_brevo_list()
        logging.info(
            "Script de synchronisation Authentik vers Brevo terminé avec succès."
        )
    except Exception as e:
        logging.error(
            f"Une erreur s'est produite pendant l'exécution du script de synchronisation : {e}",
            exc_info=True,
        )
        sys.exit(
            1
        )  # Quitter avec un code d'erreur en cas d'échec grave non géré dans la fonction principale
    sys.exit(0)  # Quitter avec succès
