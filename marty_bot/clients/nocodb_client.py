import requests
import logging

# Configure logging for the client
logger = logging.getLogger(__name__)


class NocoDBClient:
    def __init__(self, base_url: str, token: str, **kwargs):
        if not base_url:
            logger.error("NocoDB URL (base_url) is required for NocoDBClient initialization.")
            raise ValueError("NocoDB URL (base_url) is required.")
        if not token:
            logger.error("NocoDB Token is required for NocoDBClient initialization.")
            raise ValueError("NocoDB Token is required.")

        self.base_url = base_url.rstrip("/")
        self.headers = {
            "xc-token": token,
            "Content-Type": "application/json",
        }
        # Store shared view URLs if provided
        self.shared_view_projects_url = kwargs.get("shared_view_projects_url")
        self.shared_view_antennes_url = kwargs.get("shared_view_antennes_url")
        self.shared_view_poles_url = kwargs.get("shared_view_poles_url")
        logger.debug(f"NocoDBClient initialized for URL: {self.base_url}")

    def _make_request(self, method: str, endpoint: str, **kwargs) -> dict | list | None:
        url = f"{self.base_url}/api/v1/db/meta/{endpoint.lstrip('/')}"
        json_params = kwargs.get("json")
        log_message = f"NoCoDB API >> Request: {method.upper()} {url} - JSON Params: {json_params}"
        logger.debug(log_message)  # Reduced log verbosity for headers
        try:
            response = requests.request(method, url, headers=self.headers, **kwargs)
            response.raise_for_status()
            if response.content:
                return response.json()
            return None
        except requests.exceptions.HTTPError as e:
            if e.response is not None:
                log_msg = f"NoCoDB API << HTTP error for {method.upper()} {url}: {e.response.status_code} - {e.response.text}"
                logger.error(log_msg)
            else:
                logger.error(f"NoCoDB API << HTTP error for {method.upper()} {url} with no response body: {e}")
        except requests.exceptions.RequestException as e:
            logger.error(f"NoCoDB API << Request exception for {method.upper()} {url}: {e}")
        except ValueError as e:
            logger.error(f"NoCoDB API << Error decoding JSON response from {method.upper()} {url}: {e}")
        return None

    def create_base(self, base_title: str, description: str = "") -> dict | None:
        payload = {"title": base_title, "description": description}
        logger.info(f"Attempting to create NoCoDB base with title: {base_title}")
        response_data = self._make_request("post", "projects/", json=payload)
        if response_data and isinstance(response_data, dict) and response_data.get("id"):
            logger.info(f"Successfully created NoCoDB base '{base_title}' with ID: {response_data['id']}")
            return response_data
        logger.warning(f"Failed to create NoCoDB base '{base_title}'. Response: {response_data}")
        return None

    def get_base_by_title(self, base_title: str) -> dict | None:
        logger.debug(f"Attempting to find NoCoDB base with title: {base_title}")
        response_data = self._make_request("get", "projects/")
        if response_data and isinstance(response_data, dict) and "list" in response_data:
            for base in response_data["list"]:
                if base.get("title") == base_title:
                    logger.debug(f"Found NoCoDB base '{base_title}' with ID: {base['id']}")
                    return base
            logger.debug(f"NoCoDB base with title '{base_title}' not found.")
        else:
            logger.warning(f"Failed to list NoCoDB bases. Response: {response_data}")
        return None

    def invite_user_to_base(self, base_id: str, email: str, role: str) -> bool:
        if not base_id:
            logger.error("base_id is required to invite user.")
            return False
        payload = {"email": email, "roles": role}
        logger.info(f"Attempting to invite user '{email}' to NoCoDB project ID '{base_id}' with role '{role}'")
        endpoint = f"projects/{base_id}/users"
        response_data = self._make_request("post", endpoint, json=payload)
        if response_data and isinstance(response_data, dict) and "msg" in response_data:
            logger.info(f"Successfully invited user '{email}' to base ID '{base_id}'. Message: {response_data['msg']}")
            return True
        logger.warning(f"Failed to invite user '{email}' to base ID '{base_id}'. Response: {response_data}")
        return False

    def update_base_user(self, base_id: str, user_id: str, role: str) -> bool:
        if not base_id:
            logger.error("base_id is required to update user role.")
            return False
        payload = {"roles": role}
        logger.info(f"Attempting to update user ID '{user_id}' in NoCoDB project ID '{base_id}' to role '{role}'")
        endpoint = f"projects/{base_id}/users/{user_id}"
        response_data = self._make_request("patch", endpoint, json=payload)
        if response_data and isinstance(response_data, dict) and "msg" in response_data:
            logger.info(
                f"Successfully updated user ID '{user_id}' in base ID '{base_id}'. Message: {response_data['msg']}"
            )
            return True
        logger.warning(f"Failed to update user ID '{user_id}' in base ID '{base_id}'. Response: {response_data}")
        return False

    def list_base_users(self, base_id: str) -> list[dict]:
        if not base_id:
            logger.error("base_id is required to list users.")
            return []
        logger.debug(f"Listing users for NoCoDB project ID '{base_id}'")
        endpoint = f"projects/{base_id}/users"
        response_data = self._make_request("get", endpoint)
        if (
            response_data
            and isinstance(response_data, dict)
            and "users" in response_data
            and "list" in response_data["users"]
        ):
            users_list = response_data["users"]["list"]
            logger.debug(f"Found {len(users_list)} users for base ID '{base_id}'.")
            return users_list
        logger.warning(f"Failed to list users for base ID '{base_id}'. Response: {response_data}")
        return []

    def delete_base_user(self, base_id: str, user_id: str) -> bool:
        logger.info(
            f"Attempting to remove user ID '{user_id}' from NoCoDB base ID '{base_id}' by setting role to 'no-access'."
        )
        return self.update_base_user(base_id, user_id, role="no-access")

    def get_user_by_email_in_base(self, base_id: str, email: str) -> dict | None:
        if not base_id:
            logger.error("base_id is required to get user by email.")
            return None
        logger.debug(f"Searching for user with email '{email}' in project ID '{base_id}'.")
        users = self.list_base_users(base_id)
        for user in users:
            if user.get("email", "").lower() == email.lower():
                logger.debug(f"Found user '{email}' with ID '{user.get('id')}' in project '{base_id}'.")
                return user
        logger.debug(f"User with email '{email}' not found in project ID '{base_id}'.")
        return None

    def create_table_in_project(self, project_id: str, table_name: str, columns: list = None) -> dict | None:
        if not project_id:
            logger.error("project_id is required to create a table.")
            return None
        if not table_name:
            logger.error("table_name is required to create a table.")
            return None
        logger.info(f"Attempting to create table '{table_name}' in project ID '{project_id}'.")
        default_columns = columns or [
            {
                "column_name": "id",
                "title": "Id",
                "dt": "int",
                "pk": True,
                "ai": True,
                "uidt": "ID",
                "ct": "int(11)",
                "un": True,
                "rqd": True,
                "dtx": "integer",
                "dtxp": "11",
                "altered": 1,
                "cdf": None,
                "ck": False,
                "clen": None,
                "nrqd": False,
                "ns": 0,
                "uicn": "",
                "uip": "",
            },
            {
                "column_name": "title",
                "title": "Title",
                "dt": "varchar",
                "uidt": "SingleLineText",
                "ct": "varchar(45)",
                "dtx": "specificType",
                "dtxp": "45",
                "rqd": False,
                "altered": 1,
                "cdf": None,
                "ck": False,
                "clen": 45,
                "pk": False,
                "ai": False,
                "un": False,
                "nrqd": True,
                "ns": None,
                "uicn": "",
                "uip": "",
            },
            {
                "column_name": "created_at",
                "title": "CreatedAt",
                "dt": "timestamp",
                "uidt": "DateTime",
                "ct": "varchar(45)",
                "dtx": "specificType",
                "cdf": "CURRENT_TIMESTAMP",
                "rqd": False,
                "altered": 1,
                "ck": False,
                "clen": 45,
                "pk": False,
                "ai": False,
                "un": False,
                "nrqd": True,
                "ns": None,
                "uicn": "",
                "uip": "",
            },
            {
                "column_name": "updated_at",
                "title": "UpdatedAt",
                "dt": "timestamp",
                "uidt": "DateTime",
                "ct": "varchar(45)",
                "dtx": "specificType",
                "cdf": "CURRENT_TIMESTAMP on update CURRENT_TIMESTAMP",
                "rqd": False,
                "altered": 1,
                "ck": False,
                "clen": 45,
                "pk": False,
                "ai": False,
                "un": False,
                "nrqd": True,
                "ns": None,
                "uicn": "",
                "uip": "",
            },
        ]
        payload = {"table_name": table_name, "title": table_name, "columns": default_columns}
        endpoint = f"projects/{project_id}/tables"
        response_data = self._make_request("post", endpoint, json=payload)
        if response_data:
            if response_data.get("id"):
                logger.info(
                    f"Successfully created/ensured NocoDB table '{table_name}' with ID: {response_data.get('id')} in project {project_id}."
                )
            elif "error" in response_data or "message" in response_data:
                logger.warning(
                    f"NocoDB responded for table '{table_name}': {response_data.get('error') or response_data.get('message')}"
                )  # noqa: E501
            return response_data
        logger.warning(
            f"Failed to create NocoDB table '{table_name}' in project {project_id} or no response."
        )  # noqa: E501
        return None


if __name__ == "__main__":
    pass
