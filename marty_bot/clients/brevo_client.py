import logging
from enum import Enum
from typing import Optional

import requests


class BrevoAction(Enum):
    CONTACT_ADDED = "USER_ENSURED_IN_BREVO_LIST"
    CONTACT_REMOVED = "USER_REMOVED_FROM_BREVO_LIST"
    FAILED_TO_ENSURE_CONTACT = "FAILED_TO_ENSURE_IN_BREVO_LIST"
    FAILED_TO_REMOVE_CONTACT = "FAILED_TO_REMOVE_FROM_BREVO_LIST"


class BrevoClient:
    def __init__(self, api_url: str, api_key: str):
        if not api_url:
            raise ValueError("Brevo API URL cannot be empty.")
        if not api_key:
            raise ValueError("Brevo API Key cannot be empty.")
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key
        self.headers = {
            "accept": "application/json",
            "api-key": self.api_key,
            "content-type": "application/json",
        }
        logging.info("BrevoClient initialized.")

    def _make_request(self, method: str, endpoint: str, json_data=None, params=None) -> tuple[int, dict | list | None]:
        """Helper function to make HTTP requests to Brevo API."""
        url = f"{self.api_url}/{endpoint.lstrip('/')}"
        logging.debug(f"Brevo API >> Request: {method.upper()} {url}, Params: {params}, JSON: {json_data}")
        try:
            response = requests.request(method, url, headers=self.headers, json=json_data, params=params)
            logging.debug(f"Brevo API << Response: Status={response.status_code}, Content='{response.text[:200]}...'")
            response.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)
            if response.status_code == 204:  # No content
                return response.status_code, None
            return response.status_code, response.json()
        except requests.exceptions.HTTPError as e:
            logging.error(
                f"Brevo API HTTP Error for {method.upper()} {url}: {e.response.status_code} - {e.response.text}"
            )
            return (
                e.response.status_code,
                e.response.json() if e.response.content else {"error": str(e)},
            )
        except requests.exceptions.RequestException as e:
            logging.error(f"Brevo API Request Exception for {method.upper()} {url}: {e}")
            return 500, {"error": str(e)}  # Generic server error for other request exceptions
        except ValueError as e:  # Includes JSONDecodeError
            logging.error(f"Brevo API JSON Decode Error for {method.upper()} {url}: {e}")
            return 500, {"error": f"JSON decode error: {e}"}

    def get_lists(self, name: Optional[str] = None) -> list[dict] | None:
        """
        Retrieves lists from Brevo. If a name is provided, it returns a list containing the single matching list object.
        If no name is provided, it returns all lists.
        """
        if name:
            logging.info(f"Attempting to find Brevo list with name: '{name}'")
        else:
            logging.info("Fetching all Brevo lists...")

        all_lists = []
        processed_list_name = name.strip().lower() if name else None
        limit = 50
        offset = 0

        while True:
            params = {"limit": limit, "offset": offset}
            status_code, data = self._make_request("GET", "contacts/lists", params=params)

            if status_code == 200 and data and "lists" in data:
                lists_on_page = data["lists"]

                if processed_list_name:
                    for lst in lists_on_page:
                        if lst.get("name", "").strip().lower() == processed_list_name:
                            logging.info(f"Found Brevo list '{name}' with ID {lst['id']}.")
                            return [lst]
                else:
                    all_lists.extend(lists_on_page)

                if len(lists_on_page) < limit:
                    break
                offset += limit
            else:
                logging.error(
                    f"Failed to fetch Brevo lists at offset {offset}. Status: {status_code}, Response: {data}"
                )
                return None

        if name:
            logging.info(f"Brevo list '{name}' not found after checking all pages.")
            return []

        logging.info(f"Successfully fetched {len(all_lists)} Brevo lists.")
        return all_lists

    def get_list_by_name(self, list_name: str) -> dict | None:
        """
        Retrieves a specific list by its name.
        :param list_name: The name of the list to find.
        :return: The list object if found, None otherwise.
        """
        lists = self.get_lists(name=list_name)
        if lists:
            return lists[0]
        return None

    def create_list(self, list_name: str, folder_id: int = 1) -> dict | None:
        """
        Creates a contact list in Brevo.
        folder_id defaults to a common default if not specified.
        Returns the created list object or None on failure.
        """
        logging.info(f"Creating Brevo list with name: '{list_name}' in folder ID {folder_id}")
        payload = {
            "name": list_name,
            "folderId": folder_id,
        }  # Default folder ID, adjust if necessary
        status_code, data = self._make_request("POST", "contacts/lists", json_data=payload)

        if status_code == 201 and data and "id" in data:
            logging.info(f"Brevo list '{list_name}' created successfully with ID {data['id']}.")
            # The response from create list is just {"id": 123}, so we fetch the full list object
            return self.get_list_by_id(data["id"])
        elif status_code == 400 and data and "code" in data and data["code"] == "duplicate_parameter":
            logging.warning(f"Brevo list '{list_name}' already exists. Attempting to fetch it.")
            lists = self.get_lists(name=list_name)
            return lists[0] if lists else None
        else:
            logging.error(f"Failed to create Brevo list '{list_name}'. Status: {status_code}, Response: {data}")
            return None

    def get_list_by_id(self, list_id: int) -> dict | None:
        """Retrieves a specific list by its ID."""
        logging.info(f"Fetching Brevo list with ID: {list_id}")
        status_code, data = self._make_request("GET", f"contacts/lists/{list_id}")
        if status_code == 200 and data:
            return data
        logging.warning(f"Could not retrieve list with ID {list_id}. Status: {status_code}")
        return None

    def get_all_lists(self) -> list[dict] | None:
        """
        Retrieves all contact lists, handling pagination.
        Returns a list of list objects or None on failure.
        """
        logging.info("Fetching all Brevo lists...")
        all_lists = []
        limit = 50
        offset = 0

        while True:
            params = {"limit": limit, "offset": offset}
            status_code, data = self._make_request("GET", "contacts/lists", params=params)

            if status_code == 200 and data and "lists" in data:
                page_lists = data["lists"]
                if not page_lists:
                    break
                all_lists.extend(page_lists)
                offset += len(page_lists)
                if len(page_lists) < limit:
                    break
            else:
                logging.error(
                    f"Failed to fetch Brevo lists at offset {offset}. Status: {status_code}, Response: {data}"
                )
                return None

        logging.info(f"Successfully fetched {len(all_lists)} Brevo lists.")
        return all_lists

    def add_contact_to_list(
        self,
        email: str,
        list_id: int,
        attributes: dict = None,
        update_enabled: bool = True,
    ) -> bool:
        """
        Adds a contact to a specific list.
        Optionally allows setting contact attributes and enabling/disabling contact update.
        """
        logging.info(f"Adding contact '{email}' to Brevo list ID {list_id}")
        payload = {
            "email": email,
            "listIds": [list_id],
            "updateEnabled": update_enabled,
        }
        if attributes:
            payload["attributes"] = attributes

        # Using POST /contacts endpoint as it's robust for adding/updating contacts and adding to list.
        status_code, data = self._make_request("POST", "contacts", json_data=payload)

        if status_code == 201:  # Contact created and added to list
            logging.info(f"Contact '{email}' created and added to list ID {list_id}.")
            return True
        elif status_code == 204:  # Contact updated and added to list (or already in list and updated)
            logging.info(f"Contact '{email}' updated and ensured in list ID {list_id}.")
            return True
        # Brevo might return 400 if email is invalid, or other errors.
        # The _make_request logs errors, here we just return success/failure.
        logging.error(f"Failed to add contact '{email}' to list ID {list_id}. Status: {status_code}, Response: {data}")
        return False

    def remove_contact_from_list(self, email: str, list_id: int) -> bool:
        """
        Removes a contact from a specific list.
        Note: Brevo API for removing from a *specific list* involves adding the contact to a list of IDs *not* to be part of.
        A more direct way is to use "unlinkListIds" when creating/updating a contact, or manage all list memberships at once.
        The endpoint `DELETE /contacts/{identifier}/lists/{listId}` is not standard for Brevo.
        Instead, we update the contact and specify which lists they should *not* be part of, or remove them from all.

        Simpler approach: Update contact, removing them from the specified list.
        The endpoint `POST /contacts` with `unlinkListIds` is suitable.
        If the contact only exists in this list and should be deleted, use DELETE /contacts/{identifier}.
        For this function, we'll just remove from the list.
        """
        logging.info(f"Removing contact '{email}' from Brevo list ID {list_id}")

        # To remove a contact from a specific list, you update the contact and use `unlinkListIds`.
        payload = {"unlinkListIds": [list_id]}
        # The identifier for the contact can be their email.
        # PUT /contacts/{identifier} where identifier is URL-encoded email
        encoded_email = requests.utils.quote(email)
        status_code, data = self._make_request("PUT", f"contacts/{encoded_email}", json_data=payload)

        if status_code == 204:  # Successfully updated (contact unlinked from list)
            logging.info(f"Contact '{email}' successfully unlinked/removed from list ID {list_id}.")
            return True
        elif status_code == 404:  # Contact not found
            logging.warning(f"Contact '{email}' not found in Brevo, cannot remove from list ID {list_id}.")
            return False  # Or True if "not being on the list" is the desired state
        else:
            logging.error(
                f"Failed to remove contact '{email}' from list ID {list_id}. Status: {status_code}, Response: {data}"
            )
            return False

    def get_contacts_from_list(self, list_id: int) -> list[str] | None:
        """
        Retrieves all contact emails from a specific list, handling pagination.
        Returns a list of contact objects or None on failure.
        """
        logging.info(f"Fetching all contacts from Brevo list ID {list_id}")
        all_contacts = []
        limit = 500  # Max limit allowed by Brevo API for this endpoint
        offset = 0

        while True:
            log_msg = f"Fetching contacts from Brevo list ID {list_id} (limit: {limit}, offset: {offset})"
            logging.debug(log_msg)
            params = {"limit": limit, "offset": offset, "sort": "desc"}
            status_code, data = self._make_request("GET", f"contacts/lists/{list_id}/contacts", params=params)

            if status_code == 200 and data and "contacts" in data:
                page_contacts = data["contacts"]
                if not page_contacts:
                    logging.info(
                        f"Finished fetching contacts for list ID {list_id}. Total contacts fetched: {len(all_contacts)}"
                    )
                    break

                all_contacts.extend(page_contacts)

                if len(page_contacts) < limit:
                    logging.info(
                        f"Finished fetching contacts for list ID {list_id} (last page had {len(page_contacts)} items). Total contacts fetched: {len(all_contacts)}"
                    )
                    break
                offset += len(page_contacts)
            else:
                logging.error(
                    f"Failed to fetch contacts from list ID {list_id} at offset {offset}. Status: {status_code}, Response: {data}"
                )
                return None

        return all_contacts

    def delete_list(self, list_id: int) -> bool:
        """Deletes a list by its ID."""
        logging.info(f"Deleting Brevo list with ID: {list_id}")
        status_code, _ = self._make_request("DELETE", f"contacts/lists/{list_id}")
        if status_code == 204:
            logging.info(f"Brevo list ID {list_id} deleted successfully.")
            return True
        logging.error(f"Failed to delete Brevo list ID {list_id}. Status: {status_code}")
        return False

    def get_folder_id_by_name(self, folder_name: str) -> int | None:
        """
        Retrieves the ID of a folder by its name.
        Handles pagination.
        :param folder_name: The name of the folder to find.
        :return: The ID of the folder if found, None otherwise.
        """
        logging.info(f"Attempting to find Brevo folder ID for folder name: '{folder_name}'")
        limit = 50  # Brevo's default limit for folders is often 10 or 50.
        offset = 0
        total_folders = None

        while True:
            params = {"limit": limit, "offset": offset, "sort": "desc"}
            status_code, data = self._make_request("GET", "contacts/folders", params=params)

            if status_code == 200 and data and "folders" in data:
                if total_folders is None:  # First call
                    total_folders = data.get("count", 0)

                for folder in data["folders"]:
                    if folder.get("name") == folder_name:
                        folder_id = folder.get("id")
                        logging.info(f"Found Brevo folder '{folder_name}' with ID {folder_id}.")
                        return folder_id

                offset += len(data["folders"])
                if offset >= total_folders or not data["folders"]:  # No more folders or reached the end
                    break
            else:
                logging.warning(
                    f"Could not retrieve folders from Brevo or data format unexpected. Status: {status_code}, Offset: {offset}"
                )
                return None

        logging.info(f"Brevo folder '{folder_name}' not found after checking {total_folders or 0} folders.")
        return None

    def send_transactional_email(
        self,
        subject: str,
        text_content: str,
        sender_email: str,
        sender_name: str,
        to_contacts: list[dict],
        html_content: str | None = None,
    ) -> bool:
        """
        Sends a transactional email.
        :param subject: Subject of the email.
        :param text_content: Plain text content of the email.
        :param sender_email: Email address of the sender.
        :param sender_name: Name of the sender.
        :param to_contacts: List of recipient dicts, e.g., [{'email': 'recipient1@example.com'}]
        :param html_content: Optional HTML content of the email.
        :return: True if email was sent successfully (API accepted the request), False otherwise.
        """
        if not all([subject, text_content, sender_email, to_contacts]):  # html_content is optional
            logging.error("Send email failed: Missing subject, text_content (fallback), sender_email, or to_contacts.")
            return False

        payload = {
            "sender": {"email": sender_email, "name": sender_name},
            "to": to_contacts,
            "subject": subject,
            "textContent": text_content,
        }
        if html_content:
            payload["htmlContent"] = html_content

        log_message = (
            f"Attempting to send transactional email. Subject: '{subject}', To: {len(to_contacts)} recipients."
        )
        if html_content:
            log_message += " (HTML content provided)"
        logging.info(log_message)
        status_code, data = self._make_request("POST", "smtp/email", json_data=payload)

        # Brevo API returns 201 Created if the email is accepted for sending
        if status_code == 201 and data and (data.get("messageId") or data.get("messageIds")):
            msg_id = data.get("messageId") or data.get("messageIds")
            logging.info(f"Transactional email accepted for sending. Message ID(s): {msg_id}")
            return True
        else:
            logging.error(f"Failed to send transactional email. Status: {status_code}, Response: {data}")
            return False


if __name__ == "__main__":
    # Example Usage (requires .env file with BREVO_API_URL and BREVO_API_KEY)
    # Ensure to install python-dotenv: pip install python-dotenv
    import os

    from dotenv import load_dotenv

    load_dotenv()

    brevo_url = os.getenv("BREVO_API_URL")
    brevo_key = os.getenv("BREVO_API_KEY")

    if not brevo_url or not brevo_key:
        print("BREVO_API_URL and BREVO_API_KEY must be set in .env file for testing.")
    else:
        logging.basicConfig(level=logging.INFO)
        client = BrevoClient(api_url=brevo_url, api_key=brevo_key)

        test_list_name = "Test List MartyBot"
        test_email_1 = "test1.marty@example.com"
        test_email_2 = "test2.marty@example.com"
        created_list_id = None

        try:
            # 1. Create a list
            print(f"\n--- Creating list: {test_list_name} ---")
            list_obj = client.create_list(test_list_name)
            if list_obj and list_obj.get("id"):
                created_list_id = list_obj["id"]
                print(f"List '{test_list_name}' ID: {created_list_id} (ensured/created)")

                # 2. Add contacts to the list
                print(f"\n--- Adding {test_email_1} to list {created_list_id} ---")
                if client.add_contact_to_list(test_email_1, created_list_id):
                    print(f"Added {test_email_1} to list {created_list_id}")
                else:
                    print(f"Failed to add {test_email_1} to list {created_list_id}")

                print(f"\n--- Adding {test_email_2} to list {created_list_id} ---")
                if client.add_contact_to_list(test_email_2, created_list_id):
                    print(f"Added {test_email_2} to list {created_list_id}")
                else:
                    print(f"Failed to add {test_email_2} to list {created_list_id}")

                # 3. Get contacts from the list
                print(f"\n--- Getting contacts from list ID {created_list_id} ---")
                contacts = client.get_contacts_from_list(created_list_id)
                if contacts is not None:
                    print(f"Contacts in list {created_list_id}: {len(contacts)}")
                    for contact in contacts:
                        print(f"  - {contact.get('email')}")
                else:
                    print(f"Could not fetch contacts from list {created_list_id}")

                # 4. Remove one contact from the list
                print(f"\n--- Removing {test_email_1} from list {created_list_id} ---")
                if client.remove_contact_from_list(test_email_1, created_list_id):
                    print(f"Removed {test_email_1} from list {created_list_id}")
                else:
                    print(f"Failed to remove {test_email_1} from list {created_list_id}")

                # 5. Get contacts again to verify
                print(f"\n--- Getting contacts from {created_list_id} (after removal) ---")
                contacts_after_removal = client.get_contacts_from_list(created_list_id)
                if contacts_after_removal is not None:
                    print(f"List {created_list_id} contacts: {len(contacts_after_removal)}")  # noqa: E501
                    for contact in contacts_after_removal:
                        print(f"  - {contact.get('email')}")
                else:
                    print(f"Could not fetch contacts from list {created_list_id}")

            else:
                print(f"Could not create or ensure list '{test_list_name}'. Further tests skipped.")

        except Exception as e:
            print(f"An error occurred during testing: {e}")
        finally:
            # Cleanup: Delete the test list if it was created
            if created_list_id:
                print(f"\n--- Attempting to delete list ID {created_list_id} ---")
                if client.delete_list(created_list_id):
                    print(f"Successfully deleted list ID {created_list_id}.")
                else:
                    print(f"Failed to delete list ID {created_list_id}.")  # noqa: E501
            # Cleanup: Delete test contacts if they exist (optional, Brevo might handle this when list is deleted or if they are test contacts)
            # This part is more complex as contacts exist independently of lists.
            # For this example, we'll skip explicit contact deletion.
            # print(f"\n--- Attempting to delete contact {test_email_1} ---")
            # client.delete_contact(test_email_1) # Assuming a delete_contact method
            # print(f"\n--- Attempting to delete contact {test_email_2} ---")
            # client.delete_contact(test_email_2)
            print("\n--- Test script finished ---")
