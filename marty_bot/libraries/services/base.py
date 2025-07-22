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
        email_to_authentik_user_pk_map,
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

    async def differential_sync(self):
        raise NotImplementedError
