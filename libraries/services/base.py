from libraries.services.mattermost import slugify


class Service:
    """
    Base class for all services that need to be synchronized.
    """

    SERVICE_NAME = "base"

    def __init__(self, client, mattermost_client, permissions_matrix, mm_team_id):
        self.client = client
        self.mattermost_client = mattermost_client
        self.permissions_matrix = permissions_matrix
        self.mm_team_id = mm_team_id

    async def group_sync(
        self,
        base_name,
        entity_config,
        all_authentik_groups_by_name,
        std_mm_users_in_channel,
        adm_mm_users_in_channel,
        mm_users_for_services,
        std_mm_channel_name_for_log,
        entity_key,
    ):
        """
        This method should be implemented by each service to synchronize groups.
        """
        raise NotImplementedError

    async def differential_sync(self, mm_channel_members: dict):
        raise NotImplementedError

    def get_mm_users_for_entity(
        self,
        base_name: str,
        entity_config: dict,
        all_mm_channel_members: dict,
    ) -> tuple[dict, list, list]:
        """
        Gathers Mattermost users for a given entity from pre-fetched channel member data.
        """
        std_config = entity_config.get("standard", {})
        admin_config = entity_config.get("admin")

        std_mm_channel_name = std_config.get("mattermost_channel_name_pattern", "{base_name}").format(
            base_name=base_name
        )
        std_mm_channel = self.mattermost_client.get_channel_by_name(self.mm_team_id, slugify(std_mm_channel_name))
        std_mm_users_in_channel = all_mm_channel_members.get(std_mm_channel["id"], []) if std_mm_channel else []

        adm_mm_users_in_channel = []
        if admin_config:
            adm_mm_channel_name = admin_config.get("mattermost_channel_name_pattern", "{base_name} Admin").format(
                base_name=base_name
            )
            adm_mm_channel = self.mattermost_client.get_channel_by_name(self.mm_team_id, slugify(adm_mm_channel_name))
            adm_mm_users_in_channel = all_mm_channel_members.get(adm_mm_channel["id"], []) if adm_mm_channel else []

        mm_users_for_services = {}
        for mm_user in std_mm_users_in_channel:
            email = mm_user.get("email", "").lower()
            if email:
                mm_users_for_services[email] = {
                    "username": mm_user.get("username"),
                    "mm_user_id": mm_user.get("id"),
                    "is_admin_channel_member": False,
                }

        if admin_config:
            for mm_user in adm_mm_users_in_channel:
                email = mm_user.get("email", "").lower()
                if email:
                    existing_data = mm_users_for_services.get(email, {})
                    mm_users_for_services[email] = {
                        "username": mm_user.get("username", existing_data.get("username")),
                        "mm_user_id": mm_user.get("id", existing_data.get("mm_user_id")),
                        "is_admin_channel_member": True,
                    }

        return mm_users_for_services, std_mm_users_in_channel, adm_mm_users_in_channel
