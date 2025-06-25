# lexicon.py

LEXICON_COMMANDS_RU = {
    '/start': '🚀 Перезапустить/Начать игру',
    '/help': '📜 Справка по игре',
    '/id': '🆔 Узнать свой ID',
}

LEXICON_RU = {
    # --- Команды и основное меню ---
    'welcome': 'Прием, командир {name}. Системы активированы. War of Generals ожидает ваших приказов.',
    'welcome_back': 'С возвращением в строй, командир {name}.',
    'main_menu_text': 'Центральный штаб. Выберите сектор для инспекции:',
    'help_command_text': (
        "**📜 Устав и директивы**\n\n"
        "● **Моя база** \- Оперативная сводка по ресурсам, войскам и текущим операциям\.\n"
        "● **Здания** \- Управление инфраструктурой базы\.\n"
        "● **Казарма** \- Подготовка и мобилизация личного состава\.\n"
        "● **Рейтинг** \- Оценка эффективности командующих\.\n"
        "● **Список целей** \- Данные разведки по потенциальным противникам\.\n\n"
        "*Цель операции: достижение полного военного превосходства\!*"
    ),

    # --- Общая информация и база ---
    'base_info_title': '🏕️ **Оперативная сводка по базе**',
    'base_info_text': ('💰 **Припасы:** `{resources}`\n\n'
                       '--- **🛡️ Личный состав** ---\n'
                       '**В строю:** `{active_army}` 💂\n'
                       '**В резерве:** `{reserve_army}` 💂'),
    'construction_in_progress': '\n\n**Ведется строительство:**\n🏗️ {building_name} (завершение через: {time_left})',
    'training_in_progress': '\n\n**Идет подготовка:**\n💪 {unit_name}: {quantity} ед. (следующий через: {time_left})',
    'army_management_title': (
        '**🗂️ Управление личным составом**\n\n'
        'Перераспределите войска между штурмовыми отрядами и гарнизоном.\n\n'
        '**В строю:** `{active_army}` 💂\n'
        '**В резерве:** `{reserve_army}` 💂'
    ),
    'move_to_reserve_prompt': 'Введите численность отряда для перевода в резерв:',
    'move_to_active_prompt': 'Введите численность отряда для возвращения в строй:',
    'move_to_reserve_success': '✅ Приказ выполнен. {quantity} бойцов переведено в резерв.',
    'move_to_active_success': '✅ Приказ выполнен. {quantity} бойцов возвращено в строй.',

    # --- Здания и улучшения ---
    'buildings_menu_title': '**🏭 Управление инфраструктурой**\n\nВыберите объект для инспекции и улучшения:',
    'building_info': '**{building_name} (Уровень {level})**\n\n*{description}*',
    'builder_is_busy_long': '**Строительный отдел занят возведением другого объекта.**',
    'upgrade_info': ('\n\n--- **Проект улучшения** ---\n'
                     'Стоимость до Ур. {next_level}: **{cost}💰**\n'
                     'Время строительства: **{build_time}**'),
    'max_level_reached': '\n\n**Объект достиг максимального уровня модернизации.**',
    'upgrade_started': '✅ Приказ принят. Начата модернизация объекта «{building_name}».',


    # --- Тренировка ---
    'training_menu_title': '**Меню подготовки: {unit_name}**',
    'training_menu_stats': (
        '📊 **Тактико-технические характеристики:**\n'
        '  ❤️ Прочность брони: `{hp} HP`\n'
        '  ⚔️ Огневая мощь: `{attack} ед.`\n'
        '  📦 Грузовместимость: `{cargo} 💰`'
    ),
    'training_production_info': (
        '⏱️ **Производство:**\n'
        '  ▫️ Время подготовки: `{training_time} сек.` / ед.\n'
        '  ▫️ Стоимость: `{unit_cost} 💰` / ед.'
    ),
    'training_possibilities': (
        '💰 Ваши припасы: `{resources}`\n'
        '💪 Выбрано для подготовки: **{quantity_to_train}** / {max_can_train} 💂\n'
        '💸 Итоговая стоимость: **{total_cost} 💰**'
    ),
    'training_started': ("✅ **Приказ исполнен!** Подготовка личного состава начата.\n\n"
                         "Вы можете отслеживать процесс в оперативной сводке по базе."),

    # --- Атака и бои ---
    'attack_cooldown': ('**Перегруппировка.**\n\n'
                        'Войска восстанавливают боеспособность. '
                        'Новая атака будет возможна через: **{time_left}**'),
    'no_targets_available': 'Данные разведки отсутствуют. Потенциальных целей не обнаружено.',
    'select_target': '🎯 Выберите цель для нанесения удара:',
    'battle_report_title': '--- ⚔️ **Отчет о боевых действиях** ⚔️ ---',
    'battle_report_header': ('**Тема:** {battle_type} **{target_name}**\n'
                             '**Дата:** {datetime}\n\n'
                             '**Тип операции:** {operation_type}\n'
                             '**🍀 Фактор удачи:** **{luck_modifier:+.0%}**\n'
                             '**🎯 Итог:** **{result}**\n'),
    'battle_report_loot': ('\n--- **💰 Трофеи** ---\n'
                           '**Захвачено припасов:** **{looted_resources}💰**\n'),
    'battle_report_attacker_stats': ('\n--- **💥 Атакующие силы** ---\n'
                                     '**Командир:** {attacker_name}\n'
                                     '**Потери:** {losses} из {initial} ({loss_percent}%)'),
    'battle_report_defender_stats': ('\n--- **🛡️ Оборонительные силы** ---\n'
                                     '**Командир:** {defender_name}\n'
                                     '**Потери:** {losses} из {initial} ({loss_percent}%)'),
    'defenseless_attack_report': ('**Тема:** Атака на {target_name}\n'
                                  '**Итог:** Легкая победа!\n\n'
                                  'Сопротивление не оказано. Войска не понесли потерь.\n'
                                  '**Захвачено припасов:** **{looted_resources}💰**'),
    'attack_notification': '⚠️ **ТРЕВОГА!** Ваша база атакована противником. Получен отчет о боевых действиях.',

    # --- Рейтинги ---
    'rating_menu_title': '**🏆 Зал славы**\n\nВыберите категорию для просмотра досье:',
    'rating_power_title': '--- 🎖️ **Легендарные полководцы** ---\n*Командиры с непревзойденной военной мощью*\n\n',
    'rating_attack_wins_title': '--- ⚔️ **Великие завоеватели** ---\n*Мастера наступательных операций*\n\n',
    'rating_defense_wins_title': '--- 🛡️ **Неприступные крепости** ---\n*Генералы, чья оборона несокрушима*\n\n',
    'rating_resources_title': '--- 💰 **Военные магнаты** ---\n*Самые состоятельные командующие*\n\n',
    'rating_no_players': 'В данной категории пока нет выдающихся командиров.',
    'rating_line': '{medal} **{rank}. Генерал {name}** - {metric}: {value}\n',


    # --- Ошибки и валидация ---
    'error_positive_number_required': '❗️ Введите положительное число.',
    'error_not_enough_units_in_active': '❗️ В штурмовом отряде всего {active_army} бойцов.',
    'error_not_enough_units_in_reserve': '❗️ В резерве всего {reserve_army} бойцов.',
    'error_max_level_reached_alert': 'Достигнут максимальный уровень!',
    'error_not_enough_resources_alert': 'Недостаточно припасов!',
    'error_no_army_to_attack_alert': 'Вы не можете атаковать без армии!',
    'error_attack_on_cooldown_alert': 'Войска еще не готовы к новой атаке!',
    'error_player_data_not_found': 'Не удалось найти данные. Попробуйте /start',
    'critical_battle_error': 'Произошла критическая ошибка во время симуляции боя. Администратор уже уведомлен.',

    # --- АДМИН-ПАНЕЛЬ ---
    'admin_panel_title': '🔐 **Админ-панель**\n\nВыберите действие:',
    'admin_give_resources_title': 'Выберите ресурс для начисления:',
    'admin_select_target_prompt': 'Кому выдать `{resource_type}`?',
    'admin_enter_amount_prompt': 'Введите количество для начисления (можно отрицательное число):',
    'admin_enter_target_id_prompt': 'Введите Telegram ID игрока:',
    'admin_player_not_found': 'Игрок с таким ID не найден в базе данных.',
    'admin_give_success': '✅ Успешно!\nНачислено {amount}💰 игроку {name} (ID: {user_id}).',
    'admin_broadcast_prompt': 'Введите текст сообщения для рассылки всем игрокам:',
    'admin_broadcast_started': 'Начинаю рассылку сообщения {user_count} игрокам...',
    'admin_broadcast_success': ('✅ **Рассылка завершена!**\n\n'
                                'Успешно отправлено: {success_count}\n'
                                'Не удалось отправить: {fail_count}'),
    'admin_player_management_title': '👨‍💻 **Управление игроками**',
    'admin_enter_player_id_for_info': 'Введите ID игрока для просмотра полного досье:',
    'admin_player_dossier_title': '**Полное досье: Командир {name} (ID: {user_id})**',
    'dossier_stats': ('**Статистика:**\n'
                      '  - Побед в атаке: {attack_wins}\n'
                      '  - Побед в защите: {defense_wins}'),
    'dossier_buildings': ('**Здания:**\n'
                          '  - КЦ: {cc_level} ур.\n'
                          '  - Казармы: {barracks_level} ур.\n'
                          '  - Склад: {warehouse_level} ур.'),
    'dossier_army': ('**Армия:**\n'
                     '  - В строю: {active_army} 💂\n'
                     '  - В резерве: {reserve_army} 💂'),
    'dossier_processes': '**Активные процессы:**',
    'dossier_no_processes': 'Нет активных процессов.',
    'dossier_process_construction': '  - Строительство: {building_name} (ур. {level}), до завершения: {time_left}',
    'dossier_process_training': '  - Тренировка: {unit_name} ({quantity} шт.), до след.: {time_left}',
    'dossier_process_attack_cooldown': '  - Кулдаун атаки: Активен, осталось: {time_left}',
}