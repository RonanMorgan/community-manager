import logging
import os

from clients.authentik_client import AuthentikClient
from clients.brevo_client import BrevoClient
from dotenv import load_dotenv

# Charger les variables d'environnement depuis .env
load_dotenv()

# It's better to load environment variables inside the function or pass them as parameters,
# especially for testability. For now, we'll move them into the function.


def sync_authentik_users_to_brevo_list():
    """
    Synchronizes users from Authentik to a specific Brevo list.
    Fetches all users from Authentik and all contacts from the specified Brevo list.
    Adds users present in Authentik but not in the Brevo list to Brevo.
    """
    logging.info("Starting Authentik to Brevo users synchronization.")

    AUTHENTIK_URL = os.getenv("AUTHENTIK_URL")
    AUTHENTIK_TOKEN = os.getenv("AUTHENTIK_TOKEN")
    BREVO_API_URL = os.getenv("BREVO_API_URL")
    BREVO_API_KEY = os.getenv("BREVO_API_KEY")
    BREVO_AUTHENTIK_USERS_LIST_ID_STR = os.getenv("BREVO_AUTHENTIK_USERS_LIST_ID")

    if not all([AUTHENTIK_URL, AUTHENTIK_TOKEN, BREVO_API_URL, BREVO_API_KEY, BREVO_AUTHENTIK_USERS_LIST_ID_STR]):
        logging.error(
            "Missing one or more required environment variables for Authentik/Brevo sync: "
            "AUTHENTIK_URL, AUTHENTIK_TOKEN, BREVO_API_URL, BREVO_API_KEY, BREVO_AUTHENTIK_USERS_LIST_ID"
        )
        return

    try:
        brevo_list_id = int(BREVO_AUTHENTIK_USERS_LIST_ID_STR)
    except ValueError:
        logging.error(
            f"Invalid BREVO_AUTHENTIK_USERS_LIST_ID: '{BREVO_AUTHENTIK_USERS_LIST_ID_STR}'. Must be an integer."
        )
        return

    try:
        auth_client = AuthentikClient(base_url=AUTHENTIK_URL, token=AUTHENTIK_TOKEN)
        brevo_client = BrevoClient(api_url=BREVO_API_URL, api_key=BREVO_API_KEY)

        # 1. Récupérer tous les utilisateurs d'Authentik
        logging.info("Fetching all users from Authentik...")
        authentik_user_emails = auth_client.get_all_users_emails()
        if (
            authentik_user_emails is None
        ):  # get_all_users_emails returns [] on error, None is not expected but good to check
            logging.error("Failed to fetch users from Authentik. Aborting sync.")
            return

        if not authentik_user_emails:
            logging.info("No users found in Authentik.")
            # Decide if we should proceed to clear the Brevo list or just stop.
            # For now, let's stop if no Authentik users.
            # If the goal is to ensure Brevo list *only* contains current Authentik users,
            # then we might want to fetch Brevo list and remove users not in (empty) authentik_user_emails.
            # Current scope is to ADD missing users.
            return

        logging.info(f"Fetched {len(authentik_user_emails)} user emails from Authentik.")
        authentik_user_emails_set = set(email.lower() for email in authentik_user_emails)

        # 2. Récupérer tous les contacts de la liste Brevo
        logging.info(f"Fetching all contacts from Brevo list ID {brevo_list_id}...")
        brevo_contact_emails = brevo_client.get_contacts_from_list(brevo_list_id)
        if brevo_contact_emails is None:
            logging.error(f"Failed to fetch contacts from Brevo list ID {brevo_list_id}. Aborting sync.")
            return

        logging.info(f"Fetched {len(brevo_contact_emails)} contact emails from Brevo list {brevo_list_id}.")
        brevo_contact_emails_set = set(email.lower() for email in brevo_contact_emails)

        # 3. Comparer les listes et identifier les utilisateurs à ajouter
        users_to_add_to_brevo = authentik_user_emails_set - brevo_contact_emails_set

        if not users_to_add_to_brevo:
            logging.info("No new users from Authentik to add to Brevo list.")
        else:
            logging.info(f"Found {len(users_to_add_to_brevo)} users to add to Brevo list: {users_to_add_to_brevo}")
            added_count = 0
            failed_count = 0
            for email_to_add in users_to_add_to_brevo:
                logging.debug(f"Adding '{email_to_add}' to Brevo list {brevo_list_id}.")
                # The add_contact_to_list method in the client already handles logging for success/failure per contact
                if brevo_client.add_contact_to_list(email=email_to_add, list_id=brevo_list_id):
                    added_count += 1
                else:
                    failed_count += 1
            logging.info(f"Finished adding users to Brevo. Added: {added_count}, Failed: {failed_count}.")

        # (Optional) Step 4: Identify users to remove from Brevo list
        # users_to_remove_from_brevo = brevo_contact_emails_set - authentik_user_emails_set
        # if users_to_remove_from_brevo:
        #     logging.info(f"Found {len(users_to_remove_from_brevo)} users to remove from Brevo list.")
        #     for email_to_remove in users_to_remove_from_brevo:
        #         brevo_client.remove_contact_from_list(email_to_remove, brevo_list_id) # Implement if needed

        logging.info("Authentik to Brevo users synchronization finished.")

    except (
        ValueError
    ) as ve:  # Handles AuthentikClient/BrevoClient init errors if URLs/tokens are invalid after load_dotenv
        logging.error(f"Configuration error during client initialization: {ve}")
    except Exception as e:
        logging.error(f"An unexpected error occurred during Authentik to Brevo sync: {e}", exc_info=True)


if __name__ == "__main__":
    # Setup basic logging for direct script execution
    log_format = "%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s"
    logging.basicConfig(level=logging.INFO, format=log_format)

    # Example of how to run the sync
    # Ensure .env file has:
    # AUTHENTIK_URL, AUTHENTIK_TOKEN
    # BREVO_API_URL, BREVO_API_KEY
    # BREVO_AUTHENTIK_USERS_LIST_ID (the numeric ID of your Brevo list)

    print("Running Authentik to Brevo user synchronization script...")
    sync_authentik_users_to_brevo_list()
    print("Script finished.")
