import asyncio

from .base_command import BaseCommand


class HelpCommand(BaseCommand):
    def __init__(self, bot):
        super().__init__(bot)

    @property
    def command_name(self):
        return "help"

    async def _execute(self, channel_id, arg_string, user_id_who_posted):
        help_lines = ["### Commandes disponibles pour MartyBot", "---"]
        if not self.bot.command_factory.commands:
            help_lines.append("Aucune commande n'est actuellement disponible.")
        else:
            for cmd, handler_instance in sorted(self.bot.command_factory.commands.items()):
                description = ""
                docstring = handler_instance.get_help()
                if docstring:
                    first_line = docstring.strip().split("\n")[0]
                    description = f" - _{first_line}_"
                help_lines.append(f"* **`{cmd}`**{description}")
        help_lines.append("\n---")
        help_lines.append("**Exemples de création :**")
        help_lines.append(f"* `{self.bot.bot_name_mention} create_projet MonProjet1 MonProjet2`")
        help_lines.append(f"* `{self.bot.bot_name_mention} create_antenne AntenneRegionale`")
        help_lines.append(f"* `{self.bot.bot_name_mention} create_pole PoleTechnique AutrePole`")
        help_lines.append("\n**Commandes de synchronisation des droits utilisateurs :**")
        help_lines.append(f"* **`{self.bot.bot_name_mention} update_all_user_rights`**")
        help_lines.append(
            "  - _Rôle : S'assure que les utilisateurs présents dans les canaux Mattermost ont bien les accès correspondants dans Authentik et Outline._"
        )
        help_lines.append(
            "  - _Logique : Part des canaux Mattermost. Ajoute les utilisateurs aux groupes/collections distants si nécessaire, ou met à jour leurs permissions. **Ne supprime jamais d'accès.** Idéal pour ajouter rapidement des droits suite à l'ajout d'un utilisateur à un canal Mattermost._"
        )
        help_lines.append(f"* **`{self.bot.bot_name_mention} update_user_rights_and_remove`**")
        help_lines.append(
            "  - _Rôle : Effectue une synchronisation complète des droits. Garantit que les accès dans Authentik/Outline reflètent exactement la composition des canaux Mattermost._"
        )
        help_lines.append(
            "  - _Logique : Combine les actions de `update_all_user_rights` (ajouts/mises à jour depuis Mattermost) ET **supprime les accès** des utilisateurs dans Authentik/Outline/NoCoDB s'ils ne sont plus présents dans les canaux Mattermost correspondants (ou si leurs droits ont changé). C'est la commande à utiliser pour une remise en cohérence complète._"
        )
        help_lines.append(
            f"  - _Option :_ Ajoutez `nocodb=false` après la commande (ex: `{self.bot.bot_name_mention} update_user_rights_and_remove nocodb=false`) pour ignorer la synchronisation NoCoDB."
        )
        help_lines.append(
            "\n**Note :** La commande `update_user_rights_and_remove` est plus complète mais peut prendre plus de temps car elle vérifie tous les membres des services distants."
        )
        help_lines.append("\n**Commande d'envoi d'email (via Brevo) :**")
        help_lines.append(f"* **`{self.bot.bot_name_mention} send_email <Sujet> /// <Message>`**")
        help_lines.append(
            '  - _Rôle : Envoie un email via Brevo aux membres de la liste de contacts associée au canal "standard" de l\'entité._'
        )
        help_lines.append(
            '  - _Usage : Doit être exécutée depuis le canal "admin" de l\'entité (projet, pôle, antenne). Le sujet et le message sont séparés par `///`._'
        )
        help_lines.append(f"\nMentionnez-moi avec une commande, comme `{self.bot.bot_name_mention} help`.")
        help_text = "\n".join(help_lines)
        await asyncio.to_thread(self.bot.envoyer_message, channel_id, help_text)

    @staticmethod
    def get_help():
        return "Displays this help message listing all available commands."
