import logging


def check_clients(clients: dict) -> None:
    authentik_client = clients.get("authentik")
    outline_client = clients.get("outline")
    brevo_client = clients.get("brevo")
    nocodb_client = clients.get("nocodb")
    vaultwarden_client = clients.get("vaultwarden")
    # Client checks
    if not authentik_client:
        logging.error("Authentik client not provided to orchestrator. Authentik sync will be skipped.")
    if not outline_client:
        logging.info("Outline client not provided. Outline synchronization will be skipped.")
    if not brevo_client:
        logging.info("Brevo client not provided. Brevo synchronization will be skipped.")
    if not nocodb_client:
        logging.info("NocoDB client not provided. NocoDB synchronization will be skipped.")
    if not vaultwarden_client:
        logging.info("Vaultwarden client not provided. Vaultwarden synchronization will be skipped.")
