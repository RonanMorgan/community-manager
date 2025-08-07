import logging
import os

from clients.brevo_client import BrevoClient
from dotenv import load_dotenv

# Charger les variables d'environnement depuis .env
load_dotenv()

# It's better to load environment variables inside the function or pass them as parameters,
# especially for testability. For now, we'll move them into the function.

# --- Attribute Mapping ---
AUTHENTIK_TO_BREVO_ATTRIBUTE_MAPPING = {
    "attributes.ville": "CITY",
    "attributes.activity": "DOMAIN",
    "attributes.metier": "JOB",
    "attributes.exp": "EXPERIENCE",
    "attributes.sp1": "SKILLS1",
    "attributes.sp2": "SKILLS2",
    "attributes.sp3": "SKILLS3",
    "attributes.framework": "FRAMEWORK",
    "attributes.totem": "TOTEM",
}


def _map_authentik_attributes_to_brevo(authentik_attrs: dict) -> dict:
    """
    Maps Authentik attribute keys to Brevo attribute keys (in uppercase)
    and handles the 'attributes.' prefix from Authentik.
    """
    if not authentik_attrs:
        return {}

    brevo_attrs = {}
    for auth_key, auth_value in authentik_attrs.items():
        # Check if the Authentik key is in our mapping
        if auth_key in AUTHENTIK_TO_BREVO_ATTRIBUTE_MAPPING:
            brevo_key = AUTHENTIK_TO_BREVO_ATTRIBUTE_MAPPING[auth_key]
            brevo_attrs[brevo_key] = auth_value
        # else:
        # logging.debug(f"Attribute '{auth_key}' from Authentik is not mapped to Brevo. Skipping.")
    return brevo_attrs


def sync_authentik_users_to_brevo_list(authentik_users_data: list):
    """
    Synchronizes users from Authentik to a specific Brevo list, including attributes.
    Fetches all users from Authentik and all contacts from the specified Brevo list.
    Adds users present in Authentik but not in the Brevo list to Brevo.
    """
    logging.info("Starting Authentik to Brevo users synchronization with attributes.")

    BREVO_API_URL = os.getenv("BREVO_API_URL")
    BREVO_API_KEY = os.getenv("BREVO_API_KEY")
    BREVO_AUTHENTIK_USERS_LIST_ID_STR = os.getenv("BREVO_AUTHENTIK_USERS_LIST_ID")

    if not all(
        [
            BREVO_API_URL,
            BREVO_API_KEY,
            BREVO_AUTHENTIK_USERS_LIST_ID_STR,
        ]
    ):
        logging.error(
            "Missing one or more required environment variables for Brevo sync: "
            "BREVO_API_URL, BREVO_API_KEY, BREVO_AUTHENTIK_USERS_LIST_ID"
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
        brevo_client = BrevoClient(api_url=BREVO_API_URL, api_key=BREVO_API_KEY)

        if not authentik_users_data:
            logging.info("No users found in Authentik.")
            return

        logging.info(f"Received {len(authentik_users_data)} users from Authentik.")

        # Create a dictionary for quick lookup of Authentik users by email
        authentik_users_map = {
            user["email"].lower(): user["attributes"] for user in authentik_users_data if user.get("email")
        }

        # 2. Récupérer tous les contacts de la liste Brevo
        logging.info(f"Fetching all contacts from Brevo list ID {brevo_list_id}...")
        brevo_contact_emails = brevo_client.get_contacts_from_list(brevo_list_id)
        if brevo_contact_emails is None:
            logging.error(f"Failed to fetch contacts from Brevo list ID {brevo_list_id}. Aborting sync.")
            return

        logging.info(f"Fetched {len(brevo_contact_emails)} contact emails from Brevo list {brevo_list_id}.")
        brevo_contact_emails_set = set(email.lower() for email in brevo_contact_emails)

        # 3. Comparer les listes et identifier les utilisateurs à ajouter
        users_to_add_to_brevo = []
        for auth_email_lower, auth_attrs in authentik_users_map.items():
            if auth_email_lower not in brevo_contact_emails_set:
                users_to_add_to_brevo.append({"email": auth_email_lower, "attributes": auth_attrs})

        if not users_to_add_to_brevo:
            logging.info("No new users from Authentik to add to Brevo list.")
        else:
            logging.info(f"Found {len(users_to_add_to_brevo)} users to add to Brevo list.")
            added_count = 0
            failed_count = 0
            for user_data_to_add in users_to_add_to_brevo:
                email_to_add = user_data_to_add["email"]
                authentik_attrs = user_data_to_add["attributes"]

                brevo_attributes = _map_authentik_attributes_to_brevo(authentik_attrs)

                logging.debug(
                    f"Adding '{email_to_add}' to Brevo list {brevo_list_id} with attributes: {brevo_attributes}"
                )

                if brevo_client.add_contact_to_list(
                    email=email_to_add,
                    list_id=brevo_list_id,
                    attributes=brevo_attributes,
                ):
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
        logging.error(
            f"An unexpected error occurred during Authentik to Brevo sync: {e}",
            exc_info=True,
        )


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
