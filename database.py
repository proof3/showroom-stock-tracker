"""
database.py
===========

Everything that talks to the database lives in this file.

The app stores four kinds of information:

    1. genders         -> e.g. Men, Women, Boys, Girls
    2. categories      -> e.g. "Jeans" under Men, "Dresses" under Girls
    3. showrooms       -> the stores that receive stock
    4. stock_entries   -> one line every time stock is PURCHASED or
                          ALLOCATED (sent) to a showroom

Totals are never typed in by anyone. They are always calculated by adding
up the individual lines in stock_entries.

Where the data is kept
----------------------
- Online (normal use): a PostgreSQL database (for example on Supabase).
  Its address is read from the Streamlit secrets file as [database] url.
- On your own computer (testing): if no database address is set, a small
  local file called "local_test_database.sqlite" is used instead.

The SQL queries below are written so they work on both.
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy import (
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    create_engine,
    text,
)

# ---------------------------------------------------------------------------
# Constants used across the app
# ---------------------------------------------------------------------------

# The two kinds of stock entry.
ENTRY_TYPE_PURCHASE = "Purchase"
ENTRY_TYPE_ALLOCATION = "Allocation"
ALL_ENTRY_TYPES = [ENTRY_TYPE_PURCHASE, ENTRY_TYPE_ALLOCATION]

# The local file used when no online database is configured.
LOCAL_TEST_DATABASE_ADDRESS = "sqlite:///local_test_database.sqlite"

# Times are recorded in UAE time (Oman uses the same time zone).
BUSINESS_TIME_ZONE = ZoneInfo("Asia/Dubai")

# Genders loaded the very first time the app runs.
# More can be added later from the Categories screen.
STARTING_GENDERS = ["Men", "Women", "Boys", "Girls"]

# Showrooms are NOT listed in the code. They live only in the database and
# are added from the Categories screen ("Add a showroom").


# ---------------------------------------------------------------------------
# Table definitions
# ---------------------------------------------------------------------------
# These describe the shape of each table. They are only used to create the
# tables the first time the app runs (see create_tables_if_missing).

table_definitions = MetaData()

genders_table = Table(
    "genders",
    table_definitions,
    Column("gender_id", Integer, primary_key=True, autoincrement=True),
    Column("gender_name", String(50), nullable=False, unique=True),
)

categories_table = Table(
    "categories",
    table_definitions,
    Column("category_id", Integer, primary_key=True, autoincrement=True),
    Column("gender_id", Integer, ForeignKey("genders.gender_id"), nullable=False),
    Column("category_name", String(100), nullable=False),
    # The same category name cannot appear twice under one gender.
    UniqueConstraint("gender_id", "category_name", name="one_category_name_per_gender"),
)

showrooms_table = Table(
    "showrooms",
    table_definitions,
    Column("showroom_id", Integer, primary_key=True, autoincrement=True),
    Column("showroom_name", String(100), nullable=False, unique=True),
    Column("country", String(50), nullable=False),
)

stock_entries_table = Table(
    "stock_entries",
    table_definitions,
    Column("entry_id", Integer, primary_key=True, autoincrement=True),
    Column("entry_date", Date, nullable=False),
    # Either "Purchase" or "Allocation".
    Column("entry_type", String(20), nullable=False),
    Column("category_id", Integer, ForeignKey("categories.category_id"), nullable=False),
    # Only filled in for allocations. Purchases are not tied to a showroom.
    Column("showroom_id", Integer, ForeignKey("showrooms.showroom_id"), nullable=True),
    Column("quantity", Integer, nullable=False),
    Column("note", String(500), nullable=True),
    # Name of the editor who typed the entry, and when.
    Column("entered_by", String(100), nullable=False),
    Column("entered_at", DateTime, nullable=False),
    CheckConstraint("quantity > 0", name="quantity_must_be_positive"),
)


# ---------------------------------------------------------------------------
# Connecting and first-time setup
# ---------------------------------------------------------------------------

def connect_to_database(database_address):
    """
    Open a connection to the database and make sure the tables exist.

    database_address: the database URL from the secrets file, or an empty
                      value to use the local test file.

    Returns a SQLAlchemy "engine", which the other functions use to run queries.
    """
    if not database_address:
        database_address = LOCAL_TEST_DATABASE_ADDRESS

    # Supabase gives an address starting with "postgresql://" (sometimes
    # "postgres://"). Tell SQLAlchemy to use the psycopg2 driver, which is
    # the one listed in requirements.txt.
    for address_start in ["postgresql://", "postgres://"]:
        if database_address.startswith(address_start):
            database_address = "postgresql+psycopg2://" + database_address[len(address_start):]

    # pool_pre_ping checks the connection is still alive before each use,
    # which avoids errors after the app has been idle for a while.
    database_engine = create_engine(database_address, pool_pre_ping=True)

    create_tables_if_missing(database_engine)
    load_starting_data_if_empty(database_engine)

    return database_engine


def create_tables_if_missing(database_engine):
    """Create the four tables. Tables that already exist are left untouched."""
    table_definitions.create_all(database_engine)

    # Extra safety step for Supabase (PostgreSQL only):
    # Supabase also offers its own web "Data API" to every table. Turning on
    # "row level security" with no rules blocks that route completely, so the
    # data can only be reached through this app. The app itself is not
    # affected because it connects as the owner of the tables.
    if database_engine.dialect.name == "postgresql":
        with database_engine.begin() as connection:
            for table_name in table_definitions.tables:
                connection.execute(text(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY"))


def load_starting_data_if_empty(database_engine):
    """
    The first time the app runs, fill in the starting genders.
    If the genders table already has data, nothing is changed.
    (Showrooms are never filled in by the code; they are added in the app.)
    """
    with database_engine.begin() as connection:
        number_of_genders = connection.execute(text("SELECT COUNT(*) FROM genders")).scalar()
        if number_of_genders == 0:
            for gender_name in STARTING_GENDERS:
                connection.execute(
                    text("INSERT INTO genders (gender_name) VALUES (:gender_name)"),
                    {"gender_name": gender_name},
                )


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def make_name_comparable(name):
    """
    Turn a name into a simple form used only for spotting duplicates.

    Capital letters, spaces, hyphens and full stops are ignored, so
    "T-Shirt", "t shirt" and "TSHIRT" are all treated as the same name.
    """
    comparable_name = name.lower()
    for character_to_ignore in [" ", "-", "_", "."]:
        comparable_name = comparable_name.replace(character_to_ignore, "")
    return comparable_name


def clean_up_name(name):
    """Remove extra spaces from the start, end and middle of a name."""
    return " ".join(name.split())


def current_business_time_as_text():
    """The current UAE date and time, e.g. '2026-11-04 12:10:05'."""
    return datetime.now(BUSINESS_TIME_ZONE).strftime("%Y-%m-%d %H:%M:%S")


def run_query_into_table(database_engine, sql_query, query_values=None):
    """Run a SELECT query and return the result as a pandas table (DataFrame)."""
    with database_engine.connect() as connection:
        query_result = connection.execute(text(sql_query), query_values or {})
        return pd.DataFrame(query_result.fetchall(), columns=list(query_result.keys()))


# ---------------------------------------------------------------------------
# Genders
# ---------------------------------------------------------------------------

def get_all_genders(database_engine):
    """All genders, in the order they were added. Columns: gender_id, gender_name."""
    return run_query_into_table(
        database_engine,
        "SELECT gender_id, gender_name FROM genders ORDER BY gender_id",
    )


def add_gender(database_engine, new_gender_name):
    """
    Add a new gender.

    Returns (was_added, message) so the screen can show the right message.
    """
    new_gender_name = clean_up_name(new_gender_name)
    if not new_gender_name:
        return False, "Please type a gender name."

    existing_genders = get_all_genders(database_engine)
    for existing_gender_name in existing_genders["gender_name"]:
        if make_name_comparable(existing_gender_name) == make_name_comparable(new_gender_name):
            return False, f'"{existing_gender_name}" already exists.'

    with database_engine.begin() as connection:
        connection.execute(
            text("INSERT INTO genders (gender_name) VALUES (:gender_name)"),
            {"gender_name": new_gender_name},
        )
    return True, f'Gender "{new_gender_name}" added.'


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------

def get_categories_for_gender(database_engine, gender_id):
    """Categories under one gender, A to Z. Columns: category_id, category_name."""
    return run_query_into_table(
        database_engine,
        """
        SELECT category_id, category_name
        FROM categories
        WHERE gender_id = :gender_id
        ORDER BY category_name
        """,
        {"gender_id": gender_id},
    )


def get_all_categories_with_gender(database_engine):
    """
    Every category together with its gender, for the Categories screen.
    Columns: category_id, gender_name, category_name, gender_id.
    """
    return run_query_into_table(
        database_engine,
        """
        SELECT categories.category_id,
               genders.gender_name,
               categories.category_name,
               genders.gender_id
        FROM categories
        JOIN genders ON genders.gender_id = categories.gender_id
        ORDER BY genders.gender_id, categories.category_name
        """,
    )


def find_duplicate_category_name(database_engine, gender_id, category_name, category_id_to_skip=None):
    """
    Look for a category under this gender whose name matches category_name
    (ignoring capitals, spaces and hyphens).

    category_id_to_skip is used when renaming, so a category is not reported
    as a duplicate of itself.

    Returns the existing matching name, or None if there is no duplicate.
    """
    existing_categories = get_categories_for_gender(database_engine, gender_id)
    for _, existing_category in existing_categories.iterrows():
        if existing_category["category_id"] == category_id_to_skip:
            continue
        if make_name_comparable(existing_category["category_name"]) == make_name_comparable(category_name):
            return existing_category["category_name"]
    return None


def add_category(database_engine, gender_id, new_category_name):
    """
    Add a new category under a gender.

    Returns (was_added, message, saved_category_name).
    """
    new_category_name = clean_up_name(new_category_name)
    if not new_category_name:
        return False, "Please type a category name.", None

    duplicate_name = find_duplicate_category_name(database_engine, gender_id, new_category_name)
    if duplicate_name:
        return False, f'"{duplicate_name}" already exists under this gender.', None

    with database_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO categories (gender_id, category_name) "
                "VALUES (:gender_id, :category_name)"
            ),
            {"gender_id": gender_id, "category_name": new_category_name},
        )
    return True, f'Category "{new_category_name}" added.', new_category_name


def rename_category(database_engine, category_id, gender_id, new_category_name):
    """
    Change the name of an existing category. Past entries keep pointing to
    it, so their totals simply appear under the new name.

    Returns (was_renamed, message).
    """
    new_category_name = clean_up_name(new_category_name)
    if not new_category_name:
        return False, "Please type the new name."

    duplicate_name = find_duplicate_category_name(
        database_engine, gender_id, new_category_name, category_id_to_skip=category_id
    )
    if duplicate_name:
        return False, f'"{duplicate_name}" already exists under this gender.'

    with database_engine.begin() as connection:
        connection.execute(
            text("UPDATE categories SET category_name = :category_name WHERE category_id = :category_id"),
            {"category_name": new_category_name, "category_id": category_id},
        )
    return True, f'Renamed to "{new_category_name}".'


# ---------------------------------------------------------------------------
# Showrooms
# ---------------------------------------------------------------------------

def get_all_showrooms(database_engine):
    """All showrooms, UAE first then Oman. Columns: showroom_id, showroom_name, country."""
    return run_query_into_table(
        database_engine,
        "SELECT showroom_id, showroom_name, country FROM showrooms ORDER BY country DESC, showroom_id",
    )


def add_showroom(database_engine, new_showroom_name, country):
    """
    Add a new showroom (for when a store opens).

    Returns (was_added, message).
    """
    new_showroom_name = clean_up_name(new_showroom_name)
    country = clean_up_name(country)
    if not new_showroom_name or not country:
        return False, "Please type both the showroom name and the country."

    existing_showrooms = get_all_showrooms(database_engine)
    for existing_showroom_name in existing_showrooms["showroom_name"]:
        if make_name_comparable(existing_showroom_name) == make_name_comparable(new_showroom_name):
            return False, f'"{existing_showroom_name}" already exists.'

    with database_engine.begin() as connection:
        connection.execute(
            text("INSERT INTO showrooms (showroom_name, country) VALUES (:showroom_name, :country)"),
            {"showroom_name": new_showroom_name, "country": country},
        )
    return True, f'Showroom "{new_showroom_name}" added.'


# ---------------------------------------------------------------------------
# Stock entries (purchases and allocations)
# ---------------------------------------------------------------------------

def add_stock_entry(database_engine, entry_date, entry_type, category_id, showroom_id, quantity, note, entered_by):
    """
    Save one purchase or allocation line.

    For a purchase, showroom_id should be None.
    For an allocation, showroom_id is the showroom the stock was sent to.
    """
    if entry_type == ENTRY_TYPE_PURCHASE:
        showroom_id = None

    with database_engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO stock_entries
                    (entry_date, entry_type, category_id, showroom_id,
                     quantity, note, entered_by, entered_at)
                VALUES
                    (:entry_date, :entry_type, :category_id, :showroom_id,
                     :quantity, :note, :entered_by, :entered_at)
                """
            ),
            {
                # Dates are passed as text like "2026-11-04" so the same query
                # works on both PostgreSQL and the local test file.
                "entry_date": entry_date.isoformat(),
                "entry_type": entry_type,
                "category_id": category_id,
                "showroom_id": showroom_id,
                "quantity": int(quantity),
                "note": note.strip() if note else None,
                "entered_by": entered_by,
                "entered_at": current_business_time_as_text(),
            },
        )


def update_stock_entry(database_engine, entry_id, entry_date, entry_type, category_id, showroom_id, quantity, note):
    """Correct an existing entry. The original 'entered by' name is kept."""
    if entry_type == ENTRY_TYPE_PURCHASE:
        showroom_id = None

    with database_engine.begin() as connection:
        connection.execute(
            text(
                """
                UPDATE stock_entries
                SET entry_date  = :entry_date,
                    entry_type  = :entry_type,
                    category_id = :category_id,
                    showroom_id = :showroom_id,
                    quantity    = :quantity,
                    note        = :note
                WHERE entry_id = :entry_id
                """
            ),
            {
                "entry_id": entry_id,
                "entry_date": entry_date.isoformat(),
                "entry_type": entry_type,
                "category_id": category_id,
                "showroom_id": showroom_id,
                "quantity": int(quantity),
                "note": note.strip() if note else None,
            },
        )


def delete_stock_entry(database_engine, entry_id):
    """Permanently remove one entry."""
    with database_engine.begin() as connection:
        connection.execute(
            text("DELETE FROM stock_entries WHERE entry_id = :entry_id"),
            {"entry_id": entry_id},
        )


def get_stock_entries(database_engine, start_date, end_date):
    """
    All entries between two dates (both included), newest first, with the
    gender, category and showroom names filled in.

    Columns: entry_id, entry_date, entry_type, gender_name, category_name,
             showroom_name, quantity, note, entered_by, entered_at,
             gender_id, category_id, showroom_id
    """
    entries_table = run_query_into_table(
        database_engine,
        """
        SELECT stock_entries.entry_id,
               stock_entries.entry_date,
               stock_entries.entry_type,
               genders.gender_name,
               categories.category_name,
               showrooms.showroom_name,
               stock_entries.quantity,
               stock_entries.note,
               stock_entries.entered_by,
               stock_entries.entered_at,
               genders.gender_id,
               categories.category_id,
               stock_entries.showroom_id
        FROM stock_entries
        JOIN categories     ON categories.category_id = stock_entries.category_id
        JOIN genders        ON genders.gender_id      = categories.gender_id
        LEFT JOIN showrooms ON showrooms.showroom_id  = stock_entries.showroom_id
        WHERE stock_entries.entry_date >= :start_date
          AND stock_entries.entry_date <= :end_date
        ORDER BY stock_entries.entry_date DESC, stock_entries.entry_id DESC
        """,
        {"start_date": start_date.isoformat(), "end_date": end_date.isoformat()},
    )

    # PostgreSQL returns real dates, the local test file returns text.
    # Convert both to plain dates so the rest of the app sees the same thing.
    if not entries_table.empty:
        entries_table["entry_date"] = pd.to_datetime(entries_table["entry_date"]).dt.date

    return entries_table


def get_latest_entries_by_editor(database_engine, editor_name, number_of_entries=10):
    """
    The most recent entries typed by one editor (newest first), so they can
    check what they just saved on the Add Entry screen.
    """
    entries_table = run_query_into_table(
        database_engine,
        """
        SELECT stock_entries.entry_id,
               stock_entries.entry_date,
               stock_entries.entry_type,
               genders.gender_name,
               categories.category_name,
               showrooms.showroom_name,
               stock_entries.quantity,
               stock_entries.note,
               stock_entries.entered_by,
               stock_entries.entered_at
        FROM stock_entries
        JOIN categories     ON categories.category_id = stock_entries.category_id
        JOIN genders        ON genders.gender_id      = categories.gender_id
        LEFT JOIN showrooms ON showrooms.showroom_id  = stock_entries.showroom_id
        WHERE stock_entries.entered_by = :editor_name
        ORDER BY stock_entries.entry_id DESC
        LIMIT :number_of_entries
        """,
        {"editor_name": editor_name, "number_of_entries": number_of_entries},
    )
    if not entries_table.empty:
        entries_table["entry_date"] = pd.to_datetime(entries_table["entry_date"]).dt.date
    return entries_table


def get_earliest_entry_date(database_engine):
    """The date of the oldest entry, or today's date if there are no entries yet."""
    with database_engine.connect() as connection:
        earliest_date = connection.execute(text("SELECT MIN(entry_date) FROM stock_entries")).scalar()
    if earliest_date is None:
        return date.today()
    return pd.to_datetime(earliest_date).date()


# ---------------------------------------------------------------------------
# Summary (totals)
# ---------------------------------------------------------------------------

def build_summary_table(entries_table, showroom_names_in_order):
    """
    Add up the entries into one row per category.

    entries_table:           the output of get_stock_entries (already filtered)
    showroom_names_in_order: showroom names, used as columns in this order

    Returns a table with these columns:
        Gender | Category | Total purchased | <one column per showroom> |
        Total allocated | Purchased but not yet allocated
    """
    summary_columns = (
        ["Gender", "Category", "Total purchased"]
        + list(showroom_names_in_order)
        + ["Total allocated", "Purchased but not yet allocated"]
    )
    if entries_table.empty:
        return pd.DataFrame(columns=summary_columns)

    category_key_columns = ["gender_id", "gender_name", "category_name"]

    # 1. Total purchased per category.
    purchase_lines = entries_table[entries_table["entry_type"] == ENTRY_TYPE_PURCHASE]
    purchased_per_category = (
        purchase_lines.groupby(category_key_columns)["quantity"].sum().rename("Total purchased")
    )

    # 2. Quantity allocated per category per showroom (showrooms become columns).
    allocation_lines = entries_table[entries_table["entry_type"] == ENTRY_TYPE_ALLOCATION]
    allocated_per_category_and_showroom = allocation_lines.pivot_table(
        index=category_key_columns,
        columns="showroom_name",
        values="quantity",
        aggfunc="sum",
    )

    # 3. Put both together: one row per category.
    summary_table = pd.concat(
        [purchased_per_category, allocated_per_category_and_showroom], axis=1
    )

    # Make sure every showroom has a column, even if nothing was sent there.
    for showroom_name in showroom_names_in_order:
        if showroom_name not in summary_table.columns:
            summary_table[showroom_name] = 0

    # Empty cells mean "nothing", so show them as 0.
    summary_table = summary_table.fillna(0)

    # 4. Totals.
    summary_table["Total allocated"] = summary_table[list(showroom_names_in_order)].sum(axis=1)
    summary_table["Purchased but not yet allocated"] = (
        summary_table["Total purchased"] - summary_table["Total allocated"]
    )

    # 5. Tidy up: gender and category as normal columns, sorted, whole numbers.
    summary_table = summary_table.reset_index()
    summary_table = summary_table.sort_values(["gender_id", "category_name"])
    summary_table = summary_table.rename(columns={"gender_name": "Gender", "category_name": "Category"})
    summary_table = summary_table[summary_columns]

    number_columns = summary_columns[2:]
    summary_table[number_columns] = summary_table[number_columns].astype(int)

    return summary_table.reset_index(drop=True)
