import asyncio
import logging
import os


async def create_resources_for_entity(
    base_name: str,
    entity_key: str,
    item_type_display: str,
    requesting_user_id: str | None,
    config,
    clients,
):
    """
    Helper function to create resources for a given entity type (e.g., PROJET)
    based on the new permissions matrix structure.
    """
    item_results_log = []
    entity_config = config.PERMISSIONS_MATRIX.get(entity_key)

    if not entity_config:
        msg = f":x: Configuration error: No permissions found for entity category '{entity_key}' in the matrix."
        logging.error(msg)
        item_results_log.append(msg)
        return item_results_log

    item_results_log.append(f"--- Création pour {item_type_display} **`{base_name}`** (entité: *{entity_key}*) ---")

    # Standard resources
    standard_config = entity_config.get("standard")
    if standard_config:
        std_auth_pattern = standard_config.get("authentik_group_name_pattern", "{base_name}")
        std_mm_chan_pattern = standard_config.get("mattermost_channel_name_pattern", "{base_name}")
        std_mm_chan_type = standard_config.get("mattermost_channel_type", "O")

        std_auth_name = std_auth_pattern.format(base_name=base_name)
        std_mm_chan_name = std_mm_chan_pattern.format(base_name=base_name)

        item_results_log.append(f"  - Standard (base: `{base_name}`):")
        # Authentik Group (Standard)
        auth_msg_std = f"    - Authentik Groupe `{std_auth_name}`: "
        if clients.get("authentik"):
            try:
                if clients.get("authentik").create_group(std_auth_name):
                    auth_msg_std += ":white_check_mark: Créé."
                else:
                    auth_msg_std += ":warning: Échec/Existe déjà."
            except Exception as e:
                auth_msg_std += f":x: Erreur ({e})."
        else:
            auth_msg_std += ":information_source: Client non configuré."
        item_results_log.append(auth_msg_std)

        # Mattermost Channel (Standard)
        mm_msg_std = f"    - Mattermost Canal `{std_mm_chan_name}` (type: {std_mm_chan_type}): "
        standard_channel_id = None
        if clients.get("mattermost"):
            try:
                ch_std = clients.get("mattermost").create_channel(std_mm_chan_name, channel_type=std_mm_chan_type)
                if ch_std and ch_std.get("id"):
                    standard_channel_id = ch_std["id"]
                    mm_msg_std += f":white_check_mark: Créé (ID: {standard_channel_id})."
                    if requesting_user_id and clients.get("mattermost").add_user_to_channel(
                        standard_channel_id, requesting_user_id
                    ):
                        mm_msg_std += " Demandeur ajouté."
                    elif requesting_user_id:
                        mm_msg_std += " Échec ajout demandeur."
                else:
                    mm_msg_std += ":warning: Échec/Existe déjà."
            except Exception as e:
                mm_msg_std += f":x: Erreur ({e})."
        else:
            mm_msg_std += ":information_source: Client non configuré."
        item_results_log.append(mm_msg_std)

    # Mattermost Board (from matrix)
    mm_board_config = entity_config.get("mattermost_board")
    if mm_board_config and mm_board_config.get("create"):
        board_name_pattern = mm_board_config.get("board_name_pattern", "{base_name}")
        board_name = board_name_pattern.format(base_name=base_name)
        mm_board_msg = f"    - Mattermost Board `{board_name}`: "
        if clients.get("mattermost") and standard_channel_id:
            template_id = os.getenv("PROJECT_BOARD_TEMPLATE_ID")
            if not template_id:
                mm_board_msg += ":warning: Échec - `PROJECT_BOARD_TEMPLATE_ID` non configuré."
                logging.warning("PROJECT_BOARD_TEMPLATE_ID is not set in the environment.")
            else:
                try:
                    new_board = await asyncio.to_thread(
                        clients.get("mattermost").create_board_from_template,
                        template_id,
                        board_name,
                        requesting_user_id,
                        standard_channel_id,
                    )
                    if new_board and new_board.get("id"):
                        mm_board_msg += f":white_check_mark: Créé (ID: {new_board['id']})."
                    else:
                        mm_board_msg += ":warning: Échec création."
                except Exception as e:
                    mm_board_msg += f":x: Erreur ({e})."
                    logging.error(f"Error creating Mattermost board for project '{base_name}': {e}", exc_info=True)
        else:
            mm_board_msg += ":information_source: Client non configuré."
        item_results_log.append(mm_board_msg)

    # Admin resources (if configured)
    admin_config = entity_config.get("admin")
    if admin_config:
        adm_auth_pattern = admin_config.get("authentik_group_name_pattern", "{base_name} Admin")
        adm_mm_chan_pattern = admin_config.get("mattermost_channel_name_pattern", "{base_name} Admin")
        adm_mm_chan_type = admin_config.get("mattermost_channel_type", "P")

        adm_auth_name = adm_auth_pattern.format(base_name=base_name)
        adm_mm_chan_name = adm_mm_chan_pattern.format(base_name=base_name)

        item_results_log.append(f"  - Admin (base: `{base_name}`):")
        # Authentik Group (Admin)
        auth_msg_adm = f"    - Authentik Groupe `{adm_auth_name}`: "
        if clients.get("authentik"):
            try:
                if clients.get("authentik").create_group(adm_auth_name):
                    auth_msg_adm += ":white_check_mark: Créé."
                else:
                    auth_msg_adm += ":warning: Échec/Existe déjà."
            except Exception as e:
                auth_msg_adm += f":x: Erreur ({e})."
        else:
            auth_msg_adm += ":information_source: Client non configuré."
        item_results_log.append(auth_msg_adm)

        # Mattermost Channel (Admin)
        mm_msg_adm = f"    - Mattermost Canal `{adm_mm_chan_name}` (type: {adm_mm_chan_type}): "
        if clients.get("mattermost"):
            try:
                ch_adm = clients.get("mattermost").create_channel(adm_mm_chan_name, channel_type=adm_mm_chan_type)
                if ch_adm and ch_adm.get("id"):
                    mm_msg_adm += f":white_check_mark: Créé (ID: {ch_adm['id']})."
                    if requesting_user_id and clients.get("mattermost").add_user_to_channel(
                        ch_adm["id"], requesting_user_id
                    ):
                        mm_msg_adm += " Demandeur ajouté."
                    elif requesting_user_id:
                        mm_msg_adm += " Échec ajout demandeur."
                else:
                    mm_msg_adm += ":warning: Échec/Existe déjà."
            except Exception as e:
                mm_msg_adm += f":x: Erreur ({e})."
        else:
            mm_msg_adm += ":information_source: Client non configuré."
        item_results_log.append(mm_msg_adm)

    # Outline Collection (unique per entity)
    outline_config = entity_config.get("outline")
    if outline_config:
        coll_pattern = outline_config.get("collection_name_pattern", "{base_name}")
        outline_coll_name = coll_pattern.format(base_name=base_name)

        outline_msg = f"  - Outline Collection `{outline_coll_name}`: "
        if clients.get("outline"):
            try:
                collection_obj = clients.get("outline").create_group(outline_coll_name)
                if collection_obj and collection_obj.get("id"):
                    outline_msg += ":white_check_mark: Collection assurée (créée ou existante)."
                else:
                    outline_msg += ":warning: Échec création/vérification."
            except Exception as e:
                outline_msg += f":x: Erreur ({e})."
        else:
            outline_msg += ":information_source: Client non configuré."
        item_results_log.append(outline_msg)

    # Brevo List (unique per entity)
    brevo_config = entity_config.get("brevo")
    if brevo_config:
        brevo_list_pattern = brevo_config.get("list_name_pattern", "mm_list_{base_name}")
        brevo_list_name = brevo_list_pattern.format(base_name=base_name)
        folder_name_from_matrix = brevo_config.get("folder_name")
        target_folder_id = 1

        brevo_msg = f"  - Brevo Liste `{brevo_list_name}`"

        if clients.get("brevo") and folder_name_from_matrix:
            try:
                fetched_folder_id = await asyncio.to_thread(
                    clients.get("brevo").get_folder_id_by_name, folder_name_from_matrix
                )
                if fetched_folder_id:
                    target_folder_id = fetched_folder_id
                    brevo_msg += f" (Dossier: '{folder_name_from_matrix}', ID: {target_folder_id})"
                else:
                    brevo_msg += (
                        f" (Dossier: '{folder_name_from_matrix}' introuvable, utilise défaut ID: {target_folder_id})"
                    )
                    logging.warning(
                        f"Brevo folder '{folder_name_from_matrix}' not found for list '{brevo_list_name}'. Using default folder ID {target_folder_id}."
                    )
            except Exception as e:
                brevo_msg += f" (Erreur recherche dossier '{folder_name_from_matrix}', utilise défaut ID: {target_folder_id}): {e}"
                logging.error(f"Error fetching Brevo folder ID for '{folder_name_from_matrix}': {e}")
        elif clients.get("brevo"):
            brevo_msg += f" (Dossier par défaut ID: {target_folder_id})"

        brevo_msg += ": "

        if clients.get("brevo"):
            try:
                existing_list = await asyncio.to_thread(clients.get("brevo").get_list_by_name, brevo_list_name)
                if existing_list:
                    current_folder_id = existing_list.get("folderId")
                    if current_folder_id == target_folder_id:
                        brevo_msg += f":white_check_mark: Existe déjà (ID: {existing_list['id']})."
                    else:
                        brevo_msg += f":warning: Existe déjà (ID: {existing_list['id']}) mais dans un autre dossier (ID: {current_folder_id}). Non déplacée."
                        logging.warning(
                            f"Brevo list '{brevo_list_name}' (ID: {existing_list['id']}) exists in folder {current_folder_id}, target was {target_folder_id}. List not moved or recreated."
                        )
                else:
                    created_list = await asyncio.to_thread(
                        clients.get("brevo").create_list,
                        brevo_list_name,
                        folder_id=int(target_folder_id),
                    )
                    if created_list and created_list.get("id"):
                        brevo_msg += f":white_check_mark: Créée (ID: {created_list['id']})."
                    else:
                        brevo_msg += ":warning: Échec création/vérification."
            except Exception as e:
                brevo_msg += f":x: Erreur ({e})."
        else:
            brevo_msg += ":information_source: Client non configuré."
        item_results_log.append(brevo_msg)

    # NoCoDB Base (for ANTENNE and POLES)
    nocodb_config = entity_config.get("nocodb")
    if nocodb_config and entity_key in ["ANTENNE", "POLES"]:
        base_title_pattern = nocodb_config.get("base_title_pattern", "nocodb_{base_name}")
        nocodb_base_title = base_title_pattern.format(base_name=base_name)
        nocodb_msg = f"  - NoCoDB Base `{nocodb_base_title}`: "

        if clients.get("nocodb"):
            try:
                existing_base = await asyncio.to_thread(clients.get("nocodb").get_base_by_title, nocodb_base_title)
                if existing_base:
                    nocodb_msg += f":white_check_mark: Existe déjà (ID: {existing_base['id']})."
                else:
                    created_base = await asyncio.to_thread(clients.get("nocodb").create_base, nocodb_base_title)
                    if created_base and created_base.get("id"):
                        nocodb_msg += f":white_check_mark: Créée (ID: {created_base['id']})."
                    else:
                        nocodb_msg += ":warning: Échec création."
            except Exception as e:
                nocodb_msg += f":x: Erreur ({e})."
        else:
            nocodb_msg += ":information_source: Client non configuré."
        item_results_log.append(nocodb_msg)

    # Vaultwarden Collection (unique per entity)
    vaultwarden_config = entity_config.get("vaultwarden")
    if vaultwarden_config:
        vw_coll_pattern = vaultwarden_config.get("collection_name_pattern", "Shared - {base_name}")
        vw_coll_name = vw_coll_pattern.format(base_name=base_name)

        vw_msg = f"  - Vaultwarden Collection `{vw_coll_name}`: "
        if clients.get("vaultwarden"):
            if not os.getenv("BW_PASSWORD"):
                vw_msg += ":warning: Échec - BW_PASSWORD non défini dans l'environnement."
                logging.warning(
                    f"Vaultwarden: BW_PASSWORD not set in environment. Cannot create collection '{vw_coll_name}'."
                )
            else:
                try:
                    collection_id = await asyncio.to_thread(clients.get("vaultwarden").create_collection, vw_coll_name)
                    if collection_id:
                        vw_msg += f":white_check_mark: Collection assurée (ID: {collection_id})."
                    else:
                        vw_msg += ":warning: Échec création/vérification."
                except FileNotFoundError:
                    error_message = "CLI 'bw' non trouvée."
                    vw_msg += f":x: Erreur ({error_message})."
                    logging.error(f"Vaultwarden client error for collection '{vw_coll_name}': {error_message}")
                except Exception as e:
                    vw_msg += f":x: Erreur ({e})."
                    logging.error(
                        f"Error creating Vaultwarden collection '{vw_coll_name}': {e}",
                        exc_info=True,
                    )
        else:
            vw_msg += ":information_source: Client non configuré."
        item_results_log.append(vw_msg)

    return item_results_log


async def execute_batch_create_command(
    channel_id: str,
    arg_string: str | None,
    item_type_display: str,
    entity_key: str,
    requesting_user_id: str | None,
    config,
    clients,
    bot,
):
    """Generic handler for create commands supporting multiple arguments, using new matrix structure."""
    command_name = f"create_{item_type_display.lower()}"
    if not arg_string:
        await asyncio.to_thread(
            bot.envoyer_message,
            channel_id,
            f":warning: Au moins un nom de {item_type_display} est requis. Usage: `@{config.BOT_NAME.lower()} {command_name} <Nom1> [Nom2 ...]`",
        )
        return

    base_names = arg_string.split()
    num_items = len(base_names)
    plural_s = "s" if num_items > 1 else ""

    initial_message = (
        f":hourglass_flowing_sand: Traitement de '{command_name}' pour {num_items} {item_type_display}{plural_s}: "
        f"**`{'`, `'.join(base_names)}`**..."
    )
    await asyncio.to_thread(bot.envoyer_message, channel_id, initial_message)

    entity_config = config.PERMISSIONS_MATRIX.get(entity_key)
    if not entity_config:
        await asyncio.to_thread(
            bot.envoyer_message,
            channel_id,
            f":x: Erreur: Configuration pour l'entité '{entity_key}' non trouvée dans la matrice des permissions.",
        )
        return

    overall_log_parts = [f"### Résumé global pour la commande `{command_name}`"]

    for base_name in base_names:
        logging.info(
            f"'{command_name}' command processing for: {base_name} (entity: {entity_key}) by user {requesting_user_id}"
        )
        item_log = await create_resources_for_entity(
            base_name=base_name,
            entity_key=entity_key,
            item_type_display=item_type_display,
            requesting_user_id=requesting_user_id,
            config=config,
            clients=clients,
        )
        overall_log_parts.extend(item_log)
        overall_log_parts.append("---")

    final_summary_message = "\n".join(overall_log_parts)
    await asyncio.to_thread(bot.envoyer_message, channel_id, final_summary_message)
