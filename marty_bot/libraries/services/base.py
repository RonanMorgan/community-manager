class SyncService:
    def __init__(self, client, mattermost_client, permissions_matrix, mm_team_id):
        self.client = client
        self.mattermost_client = mattermost_client
        self.permissions_matrix = permissions_matrix
        self.mm_team_id = mm_team_id

    async def differential_sync(self):
        raise NotImplementedError
