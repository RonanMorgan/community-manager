import logging
import os
from typing import List

from clients.outline_client import OutlineClient
from clients.nocodb_client import NocoDBClient
from clients.mattermost_client import MattermostClient
from clients.vaultwarden_client import VaultwardenClient
from dotenv import load_dotenv

load_dotenv()


def remove_inactive_users(services: List[str], authentik_users_data: list):
    """
    Remove users from specified services if they are not present in Authentik.
    """
    logging.info(f"Starting user removal process for services: {services}")

    try:
        if not authentik_users_data:
            logging.info("No users found in Authentik.")
            return

        authentik_user_emails = {user["email"].lower() for user in authentik_users_data if "email" in user}
        logging.info(f"Received {len(authentik_user_emails)} users from Authentik.")

        if "outline" in services:
            remove_inactive_outline_users(authentik_user_emails)

        if "nocodb" in services:
            remove_inactive_nocodb_users(authentik_user_emails)

        if "mattermost" in services:
            remove_inactive_mattermost_users(authentik_user_emails)

        if "vaultwarden" in services:
            remove_inactive_vaultwarden_users(authentik_user_emails)

        logging.info("User removal process finished.")

    except Exception as e:
        logging.error(f"An unexpected error occurred during user removal process: {e}", exc_info=True)


def remove_inactive_outline_users(authentik_user_emails: set):
    logging.info("Processing Outline user removal...")
    OUTLINE_URL = os.getenv("OUTLINE_URL")
    OUTLINE_TOKEN = os.getenv("OUTLINE_TOKEN")

    if not all([OUTLINE_URL, OUTLINE_TOKEN]):
        logging.error("Missing required environment variables for Outline: OUTLINE_URL, OUTLINE_TOKEN")
        return

    outline_client = OutlineClient(base_url=OUTLINE_URL, token=OUTLINE_TOKEN)
    outline_users = outline_client.list_users()
    if outline_users is None:
        logging.error("Failed to fetch users from Outline.")
        return

    outline_users_map = {user["email"].lower(): user["id"] for user in outline_users if "email" in user}
    logging.info(f"Found {len(outline_users_map)} users in Outline.")

    users_to_remove = [
        {"id": user_id, "email": email}
        for email, user_id in outline_users_map.items()
        if email not in authentik_user_emails
    ]

    if not users_to_remove:
        logging.info("No users to remove from Outline.")
        return

    logging.info(f"Found {len(users_to_remove)} users to remove from Outline.")
    deleted_count, failed_count = 0, 0
    for user in users_to_remove:
        logging.info(f"Removing user {user['email']} (ID: {user['id']}) from Outline.")
        if outline_client.delete_user(user["id"]):
            deleted_count += 1
        else:
            failed_count += 1
    logging.info(f"Finished removing users from Outline. Deleted: {deleted_count}, Failed: {failed_count}.")


def remove_inactive_nocodb_users(authentik_user_emails: set):
    logging.info("Processing NocoDB user removal...")
    NOCODB_URL = os.getenv("NOCODB_URL")
    NOCODB_TOKEN = os.getenv("NOCODB_TOKEN")

    if not all([NOCODB_URL, NOCODB_TOKEN]):
        logging.error("Missing required environment variables for NocoDB: NOCODB_URL, NOCODB_TOKEN")
        return

    nocodb_client = NocoDBClient(nocodb_url=NOCODB_URL, token=NOCODB_TOKEN)
    nocodb_users = nocodb_client.list_users()
    if nocodb_users is None:
        logging.error("Failed to fetch users from NocoDB.")
        return

    logging.info(f"Found {len(nocodb_users)} users in NocoDB.")

    bases_response = nocodb_client.list_bases()
    if not bases_response or "list" not in bases_response:
        logging.error("Failed to retrieve the list of bases from NocoDB.")
        return

    all_bases = bases_response["list"]

    for user in nocodb_users:
        user_email = user.get("email", "").lower()
        if user_email and user_email not in authentik_user_emails:
            user_id = user.get("id")
            logging.info(f"User {user_email} (ID: {user_id}) is inactive. Removing from all NocoDB bases.")
            for base in all_bases:
                base_id = base.get("id")
                if base_id:
                    logging.info(f"Removing user {user_email} from base {base.get('title')} (ID: {base_id}).")
                    nocodb_client.delete_user(base_id, user_id)


def remove_inactive_mattermost_users(authentik_user_emails: set):
    logging.info("Processing Mattermost user removal...")
    MATTERMOST_URL = os.getenv("MATTERMOST_URL")
    MATTERMOST_TOKEN = os.getenv("BOT_TOKEN")
    MATTERMOST_TEAM_ID = os.getenv("MATTERMOST_TEAM_ID")

    if not all([MATTERMOST_URL, MATTERMOST_TOKEN, MATTERMOST_TEAM_ID]):
        logging.error(
            "Missing required environment variables for Mattermost: MATTERMOST_URL, BOT_TOKEN, MATTERMOST_TEAM_ID"
        )
        return

    mattermost_client = MattermostClient(base_url=MATTERMOST_URL, token=MATTERMOST_TOKEN, team_id=MATTERMOST_TEAM_ID)
    mattermost_users = mattermost_client.list_users()
    if mattermost_users is None:
        logging.error("Failed to fetch users from Mattermost.")
        return

    logging.info(f"Found {len(mattermost_users)} users in Mattermost.")

    users_to_remove = [user for user in mattermost_users if user.get("email", "").lower() not in authentik_user_emails]

    if not users_to_remove:
        logging.info("No users to remove from Mattermost.")
        return

    logging.info(f"Found {len(users_to_remove)} users to remove from Mattermost.")
    deleted_count, failed_count = 0, 0
    for user in users_to_remove:
        user_id = user.get("id")
        user_email = user.get("email")
        logging.info(f"Deactivating user {user_email} (ID: {user_id}) in Mattermost.")
        if mattermost_client.delete_user(user_id):
            deleted_count += 1
        else:
            failed_count += 1
    logging.info(f"Finished deactivating users from Mattermost. Deactivated: {deleted_count}, Failed: {failed_count}.")


def remove_inactive_vaultwarden_users(authentik_user_emails: set):
    logging.info("Processing Vaultwarden user removal...")
    VAULTWARDEN_API_URL = os.getenv("VAULTWARDEN_API_URL")
    VAULTWARDEN_API_USERNAME = os.getenv("VAULTWARDEN_API_USERNAME")
    VAULTWARDEN_API_PASSWORD = os.getenv("VAULTWARDEN_API_PASSWORD")
    VAULTWARDEN_ORGANIZATION_ID = os.getenv("VAULTWARDEN_ORGANIZATION_ID")

    if not all([VAULTWARDEN_API_URL, VAULTWARDEN_API_USERNAME, VAULTWARDEN_API_PASSWORD, VAULTWARDEN_ORGANIZATION_ID]):
        logging.error("Missing required environment variables for Vaultwarden")
        return

    vaultwarden_client = VaultwardenClient(
        server_url=VAULTWARDEN_API_URL,
        api_username=VAULTWARDEN_API_USERNAME,
        api_password=VAULTWARDEN_API_PASSWORD,
        organization_id=VAULTWARDEN_ORGANIZATION_ID,
    )

    vaultwarden_users = vaultwarden_client.list_users()
    if vaultwarden_users is None:
        logging.error("Failed to fetch users from Vaultwarden.")
        return

    logging.info(f"Found {len(vaultwarden_users)} users in Vaultwarden.")

    users_to_remove = [
        user for user in vaultwarden_users if user.get("email", "").lower() not in authentik_user_emails
    ]

    if not users_to_remove:
        logging.info("No users to remove from Vaultwarden.")
        return

    logging.info(f"Found {len(users_to_remove)} users to remove from Vaultwarden.")
    deleted_count, failed_count = 0, 0
    for user in users_to_remove:
        user_id = user.get("id")
        user_email = user.get("email")
        logging.info(f"Deleting user {user_email} (ID: {user_id}) from Vaultwarden.")
        if vaultwarden_client.delete_user(user_id):
            deleted_count += 1
        else:
            failed_count += 1
    logging.info(f"Finished deleting users from Vaultwarden. Deleted: {deleted_count}, Failed: {failed_count}.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    # Example usage:
    # remove_inactive_users(['outline', 'nocodb', 'mattermost', 'vaultwarden'])
    remove_inactive_users(["outline"])
