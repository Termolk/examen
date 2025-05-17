# backend/app/seed.py
from flask.cli import AppGroup
from .extensions import db
from .models import Category  # Убедись, что Category импортируется правильно

# Создаем группу команд 'seed'
# Это позволит вызывать команду как: flask seed <sub_command>
seed_cli = AppGroup('seed')


@seed_cli.command('categories')  # Определяем подкоманду 'categories'
def seed_categories_command():
    """Заполняет базу данных начальными категориями и подкатегориями."""

    # Структура данных для категорий: { "Родительская категория": ["Подкатегория1", "Подкатегория2"], ... }
    categories_to_seed = {
        "Электроника": ["Смартфоны", "Ноутбуки", "Телевизоры", "Наушники", "Аксессуары"],
        "Книги": ["Художественная литература", "Научная литература", "Учебники", "Комиксы"],
        "Инструменты": ["Электроинструменты", "Ручные инструменты", "Измерительные инструменты"],
        "Одежда и обувь": ["Мужская одежда", "Женская одежда", "Детская одежда", "Обувь"],
        "Спорт и отдых": ["Велосипеды", "Туризм и кемпинг", "Тренажеры", "Зимние виды спорта"],
        "Дом и сад": ["Мебель", "Посуда", "Садовый инвентарь", "Декор"],
        "Хобби и творчество": ["Настольные игры", "Музыкальные инструменты", "Рукоделие"],
        "Автотовары": ["Запчасти", "Аксессуары для авто", "Автохимия"]
    }

    print("Заполнение категорий...")

    # Сначала создаем все родительские категории
    for parent_name in categories_to_seed.keys():
        parent_category = Category.query.filter_by(name=parent_name, parent_id=None).first()
        if not parent_category:
            parent_category = Category(name=parent_name)
            db.session.add(parent_category)
            print(f"Создание родительской категории: {parent_name}")
        else:
            print(f"Родительская категория '{parent_name}' уже существует.")

    # Сохраняем родительские категории, чтобы они получили ID
    try:
        db.session.commit()
        print("Родительские категории обработаны.")
    except Exception as e:
        db.session.rollback()
        print(f"Ошибка при сохранении родительских категорий: {e}")
        return  # Выходим, если не удалось сохранить родителей

    # Затем создаем подкатегории
    for parent_name, sub_names in categories_to_seed.items():
        parent_category = Category.query.filter_by(name=parent_name, parent_id=None).first()
        # Если родительская категория по какой-то причине не нашлась (не должно случиться после коммита выше)
        if not parent_category:
            print(f"Критическая ошибка: Родительская категория '{parent_name}' не найдена. Пропуск подкатегорий.")
            continue

        for sub_name in sub_names:
            # Проверяем, существует ли уже такая подкатегория у этого родителя
            subcategory = Category.query.filter_by(name=sub_name, parent_id=parent_category.id).first()
            if not subcategory:
                new_subcategory = Category(name=sub_name, parent=parent_category)  # Используем relationship 'parent'
                db.session.add(new_subcategory)
                print(f"Создание подкатегории: '{sub_name}' в '{parent_name}'")
            else:
                print(f"Подкатегория '{sub_name}' в '{parent_name}' уже существует.")

    # Сохраняем все подкатегории
    try:
        db.session.commit()
        print("Категории и подкатегории успешно добавлены в базу данных!")
    except Exception as e:
        db.session.rollback()
        print(f"Ошибка при сохранении подкатегорий: {e}")