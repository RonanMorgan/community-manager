import logging
import os

from clients.authentik_client import AuthentikClient
from clients.outline_client import OutlineClient
from dotenv import load_dotenv

load_dotenv()


def remove_inactive_users():
    """
    Remove users from services if they are not present in Authentik.
    """
    logging.info("Starting user removal process for inactive users.")

    AUTHENTIK_URL = os.getenv("AUTHENTIK_URL")
    AUTHENTIK_TOKEN = os.getenv("AUTHENTIK_TOKEN")
    OUTLINE_URL = os.getenv("OUTLINE_URL")
    OUTLINE_TOKEN = os.getenv("OUTLINE_TOKEN")

    if not all([AUTHENTIK_URL, AUTHENTIK_TOKEN, OUTLINE_URL, OUTLINE_TOKEN]):
        logging.error(
            "Missing one or more required environment variables for user removal: "
            "AUTHENTIK_URL, AUTHENTIK_TOKEN, OUTLINE_URL, OUTLINE_TOKEN"
        )
        return

    try:
        auth_client = AuthentikClient(base_url=AUTHENTIK_URL, token=AUTHENTIK_TOKEN)
        outline_client = OutlineClient(base_url=OUTLINE_URL, token=OUTLINE_TOKEN)

        # 1. Get all users from Authentik
        logging.info("Fetching all users from Authentik...")
        authentik_users = auth_client.get_all_users_data()
        if authentik_users is None:
            logging.error("Failed to fetch users from Authentik. Aborting.")
            return

        authentik_user_emails = {user['email'].lower() for user in authentik_users if 'email' in user}
        logging.info(f"Found {len(authentik_user_emails)} users in Authentik.")

        # For now, only Outline is supported. This can be extended to a loop of services.
        # 2. Get all users from Outline
        logging.info("Fetching all users from Outline...")
        outline_users = outline_client.list_users()
        if outline_users is None:
            logging.error("Failed to fetch users from Outline. Aborting.")
            return

        outline_users_map = {user['email'].lower(): user['id'] for user in outline_users if 'email' in user}
        logging.info(f"Found {len(outline_users_map)} users in Outline.")

        # 3. Identify users to remove from Outline
        users_to_remove_from_outline = []
        for email, user_id in outline_users_map.items():
            if email not in authentik_user_emails:
                users_to_remove_from_outline.append({'id': user_id, 'email': email})

        if not users_to_remove_from_outline:
            logging.info("No users to remove from Outline.")
        else:
            logging.info(f"Found {len(users_to_remove_from_outline)} users to remove from Outline.")
            deleted_count = 0
            failed_count = 0
            for user in users_to_remove_from_outline:
                logging.info(f"Removing user {user['email']} (ID: {user['id']}) from Outline.")
                if outline_client.delete_user(user['id']):
                    deleted_count += 1
                else:
                    failed_count += 1
            logging.info(f"Finished removing users from Outline. Deleted: {deleted_count}, Failed: {failed_count}.")

        logging.info("User removal process finished.")

    except Exception as e:
        logging.error(f"An unexpected error occurred during user removal process: {e}", exc_info=True)

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    remove_inactive_users()
