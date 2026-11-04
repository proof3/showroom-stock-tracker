"""
app.py
======

The screens of the Showroom Stock Tracker.

Run it on your own computer with:
    streamlit run app.py

Screens
-------
- Add entry   (editors only)  : record a purchase or an allocation to a showroom
- Summary     (everyone)      : totals per category and showroom, Excel download
- History     (everyone)      : every individual entry; editors can correct or delete
- Categories  (everyone)      : list of genders, categories and showrooms;
                                editors can add and rename

Who can do what
---------------
- Viewers can see everything but cannot change anything.
- Editors log in with their name and password and can add or change data.
Both are set up in the secrets file (see README.md).
"""

import hmac
from datetime import date, timedelta
from io import BytesIO

import pandas as pd
import streamlit as st

import database

# ---------------------------------------------------------------------------
# Page settings and constants
# ---------------------------------------------------------------------------

st.set_page_config(page_title="Showroom Stock Tracker", layout="wide")

# The extra option at the bottom of the category dropdown.
ADD_NEW_CATEGORY_OPTION = "+ Add new category"

# Names of the screens, as shown in the side menu.
PAGE_ADD_ENTRY = "Add entry"
PAGE_SUMMARY = "Summary"
PAGE_HISTORY = "History"
PAGE_CATEGORIES = "Categories"

# The values saved in the session to remember who is using the app.
ACCESS_LEVEL_VIEWER = "viewer"
ACCESS_LEVEL_EDITOR = "editor"

# Friendlier column names for tables shown on screen and in Excel.
ENTRY_COLUMN_LABELS = {
    "entry_id": "Entry #",
    "entry_date": "Date",
    "entry_type": "Type",
    "gender_name": "Gender",
    "category_name": "Category",
    "showroom_name": "Showroom",
    "quantity": "Quantity",
    "note": "Note",
    "entered_by": "Entered by",
    "entered_at": "Entered at",
}


# ---------------------------------------------------------------------------
# Reading settings from the secrets file
# ---------------------------------------------------------------------------

def read_secrets_section(section_name):
    """
    Read one section (for example [editors]) of the secrets file as a
    dictionary. Returns an empty dictionary if the file or section is missing,
    so the app still opens while testing on a computer with no secrets file.
    """
    try:
        return dict(st.secrets.get(section_name, {}))
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Database connection
# ---------------------------------------------------------------------------

@st.cache_resource
def get_database_engine():
    """
    Connect to the database once and reuse the connection for every visitor.
    (st.cache_resource keeps the result so we don't reconnect on every click.)
    """
    database_settings = read_secrets_section("database")
    database_address = database_settings.get("url", "")
    return database.connect_to_database(database_address)


# ---------------------------------------------------------------------------
# Logging in
# ---------------------------------------------------------------------------

def passwords_match(typed_password, correct_password):
    """Compare two passwords safely (hmac.compare_digest resists timing tricks)."""
    return hmac.compare_digest(typed_password.encode("utf-8"), str(correct_password).encode("utf-8"))


def show_editor_login_form():
    """Name + password form for editors. Used in the side menu and on the login page."""
    editor_passwords_by_name = read_secrets_section("editors")
    if not editor_passwords_by_name:
        st.caption("No editors have been set up yet (see README.md).")
        return

    editor_names = list(editor_passwords_by_name.keys())
    chosen_editor_name = st.selectbox("Your name", editor_names, key="login_editor_name")
    typed_password = st.text_input("Editor password", type="password", key="login_editor_password")

    if st.button("Log in as editor", key="login_editor_button"):
        if passwords_match(typed_password, editor_passwords_by_name[chosen_editor_name]):
            st.session_state["access_level"] = ACCESS_LEVEL_EDITOR
            st.session_state["editor_name"] = chosen_editor_name
            st.rerun()
        else:
            st.error("Wrong password.")


def show_login_page():
    """
    Shown only when a viewer password has been set and the visitor has not
    entered it yet. Offers the viewer password and the editor login.
    """
    st.title("Showroom Stock Tracker")
    viewer_column, editor_column = st.columns(2)

    with viewer_column:
        st.subheader("View only")
        access_settings = read_secrets_section("access")
        typed_viewer_password = st.text_input("Viewer password", type="password", key="login_viewer_password")
        if st.button("Open", key="login_viewer_button"):
            if passwords_match(typed_viewer_password, access_settings.get("viewer_password", "")):
                st.session_state["access_level"] = ACCESS_LEVEL_VIEWER
                st.rerun()
            else:
                st.error("Wrong password.")

    with editor_column:
        st.subheader("Editor")
        show_editor_login_form()


def work_out_access_level():
    """
    Decide whether the visitor is an editor, a viewer, or needs to log in.

    Returns "editor", "viewer", or None (None means: show the login page).
    """
    # Already logged in during this visit.
    if st.session_state.get("access_level"):
        return st.session_state["access_level"]

    # If no viewer password is set, anyone with the link can view.
    viewer_password = read_secrets_section("access").get("viewer_password", "")
    if not viewer_password:
        return ACCESS_LEVEL_VIEWER

    return None


def log_out():
    """Forget who is logged in and go back to the start."""
    for session_key in ["access_level", "editor_name"]:
        st.session_state.pop(session_key, None)
    st.rerun()


# ---------------------------------------------------------------------------
# Small shared helpers for the screens
# ---------------------------------------------------------------------------

def show_saved_message_if_any():
    """
    After saving, the page reloads (st.rerun). The success message is kept in
    the session so it can still be shown after the reload.
    """
    saved_message = st.session_state.pop("saved_message", None)
    if saved_message:
        st.success(saved_message)


def remember_message_for_after_reload(message):
    st.session_state["saved_message"] = message


def ask_for_date_range(label, default_start_date, default_end_date, widget_key):
    """
    Show a "from - to" date picker.

    Returns (start_date, end_date), or (None, None) while the person has only
    picked the first of the two dates.
    """
    picked_dates = st.date_input(
        label,
        value=(default_start_date, default_end_date),
        format="DD/MM/YYYY",
        key=widget_key,
    )
    if len(picked_dates) != 2:
        st.info("Pick an end date as well.")
        return None, None
    start_date, end_date = picked_dates
    return start_date, end_date


def make_entries_readable(entries_table):
    """Keep the columns people care about and give them friendly names."""
    readable_entries = entries_table[list(ENTRY_COLUMN_LABELS.keys())].copy()
    # Purchases are not tied to a showroom; show a dash instead of a blank.
    readable_entries["showroom_name"] = readable_entries["showroom_name"].fillna("—")
    readable_entries["note"] = readable_entries["note"].fillna("")
    return readable_entries.rename(columns=ENTRY_COLUMN_LABELS)


def find_position_in_list(list_of_values, value_to_find):
    """Position of a value in a list, or 0 if it is not there (used to pre-select dropdowns)."""
    try:
        return list(list_of_values).index(value_to_find)
    except ValueError:
        return 0


# ---------------------------------------------------------------------------
# Screen: Add entry (editors only)
# ---------------------------------------------------------------------------

def show_add_entry_page(database_engine, editor_name):
    st.title("Add entry")
    st.caption("Each entry is one line. The app adds them up for you on the Summary screen.")
    show_saved_message_if_any()

    # --- Date and type -----------------------------------------------------
    date_column, type_column = st.columns(2)
    with date_column:
        entry_date = st.date_input("Date", value=date.today(), format="DD/MM/YYYY", key="new_entry_date")
    with type_column:
        entry_type = st.radio(
            "Type",
            database.ALL_ENTRY_TYPES,
            horizontal=True,
            key="new_entry_type",
            help="Purchase = stock bought. Allocation = stock sent to a showroom.",
        )

    # --- Gender and category -------------------------------------------------
    gender_column, category_column = st.columns(2)

    all_genders = database.get_all_genders(database_engine)
    with gender_column:
        chosen_gender_name = st.selectbox("Gender", all_genders["gender_name"], key="new_entry_gender")
    chosen_gender_id = int(
        all_genders.loc[all_genders["gender_name"] == chosen_gender_name, "gender_id"].iloc[0]
    )

    categories_for_gender = database.get_categories_for_gender(database_engine, chosen_gender_id)
    category_options = list(categories_for_gender["category_name"]) + [ADD_NEW_CATEGORY_OPTION]

    # Each gender gets its own category dropdown, so switching gender never
    # leaves a category from the wrong gender selected.
    category_dropdown_key = f"new_entry_category_for_gender_{chosen_gender_id}"

    # If a category was just added below, select it in the dropdown.
    # (This must happen before the dropdown is drawn.)
    newly_added_category_name = st.session_state.pop("category_to_select_next", None)
    if newly_added_category_name:
        st.session_state[category_dropdown_key] = newly_added_category_name

    with category_column:
        chosen_category_name = st.selectbox(
            "Category",
            category_options,
            index=None,
            placeholder="Choose, or type to search",
            key=category_dropdown_key,
        )

        # Adding a new category without leaving this screen.
        if chosen_category_name == ADD_NEW_CATEGORY_OPTION:
            new_category_name = st.text_input(
                f"New category name for {chosen_gender_name}", key="new_category_name_on_entry_page"
            )
            if st.button("Save new category"):
                was_added, message, saved_category_name = database.add_category(
                    database_engine, chosen_gender_id, new_category_name
                )
                if was_added:
                    st.session_state["category_to_select_next"] = saved_category_name
                    st.session_state.pop("new_category_name_on_entry_page", None)
                    remember_message_for_after_reload(message)
                    st.rerun()
                else:
                    st.error(message)

    # --- Showroom (allocations only) -----------------------------------------
    chosen_showroom_id = None
    all_showrooms = database.get_all_showrooms(database_engine)
    if entry_type == database.ENTRY_TYPE_ALLOCATION:
        chosen_showroom_name = st.selectbox(
            "Showroom",
            all_showrooms["showroom_name"],
            index=None,
            placeholder="Choose a showroom",
            key="new_entry_showroom",
        )
        if chosen_showroom_name:
            chosen_showroom_id = int(
                all_showrooms.loc[all_showrooms["showroom_name"] == chosen_showroom_name, "showroom_id"].iloc[0]
            )

    # --- Quantity and note -----------------------------------------------------
    quantity_column, note_column = st.columns([1, 2])
    with quantity_column:
        quantity = st.number_input(
            "Quantity (pieces)", min_value=1, step=1, value=None, placeholder="e.g. 24", key="new_entry_quantity"
        )
    with note_column:
        note = st.text_input("Note (optional)", placeholder="e.g. supplier name or delivery note number", key="new_entry_note")

    # --- Save --------------------------------------------------------------
    if st.button("Save entry", type="primary"):
        # Check everything needed has been filled in.
        problems = []
        if not chosen_category_name or chosen_category_name == ADD_NEW_CATEGORY_OPTION:
            problems.append("choose a category")
        if entry_type == database.ENTRY_TYPE_ALLOCATION and chosen_showroom_id is None:
            problems.append("choose a showroom")
        if not quantity:
            problems.append("enter a quantity")

        if problems:
            st.error("Please " + " and ".join(problems) + ".")
        else:
            chosen_category_id = int(
                categories_for_gender.loc[
                    categories_for_gender["category_name"] == chosen_category_name, "category_id"
                ].iloc[0]
            )
            database.add_stock_entry(
                database_engine,
                entry_date=entry_date,
                entry_type=entry_type,
                category_id=chosen_category_id,
                showroom_id=chosen_showroom_id,
                quantity=quantity,
                note=note,
                entered_by=editor_name,
            )

            # Describe what was saved, e.g. "Saved: Allocation · Men · Jeans → Showroom A · 24 pcs"
            saved_description = f"Saved: {entry_type} · {chosen_gender_name} · {chosen_category_name}"
            if entry_type == database.ENTRY_TYPE_ALLOCATION:
                saved_description += f" → {chosen_showroom_name}"
            saved_description += f" · {int(quantity)} pcs"
            remember_message_for_after_reload(saved_description)

            # Clear only the quantity and note. Date, type, gender, category and
            # showroom stay as they are, so the next entry is quick to add.
            st.session_state.pop("new_entry_quantity", None)
            st.session_state.pop("new_entry_note", None)
            st.rerun()

    # --- The editor's latest entries, to double-check -------------------------
    st.divider()
    st.subheader("Your latest entries")
    latest_entries = database.get_latest_entries_by_editor(database_engine, editor_name)
    if latest_entries.empty:
        st.caption("Nothing entered yet.")
    else:
        st.dataframe(make_entries_readable(latest_entries), hide_index=True, width="stretch")
        st.caption("To correct or delete an entry, go to the History screen.")


# ---------------------------------------------------------------------------
# Screen: Summary (everyone)
# ---------------------------------------------------------------------------

def create_excel_file(summary_table, entries_table):
    """
    Build an Excel file in memory with two sheets:
      - "Summary": the totals table
      - "Entries": every individual line behind those totals
    Returns the file contents as bytes, ready to download.
    """
    excel_file_in_memory = BytesIO()
    with pd.ExcelWriter(excel_file_in_memory, engine="openpyxl") as excel_writer:
        summary_table.to_excel(excel_writer, sheet_name="Summary", index=False)
        entries_table.to_excel(excel_writer, sheet_name="Entries", index=False)
    return excel_file_in_memory.getvalue()


def show_summary_page(database_engine):
    st.title("Summary")

    # --- Filters -------------------------------------------------------------
    date_column, gender_column = st.columns(2)
    with date_column:
        start_date, end_date = ask_for_date_range(
            "Dates",
            default_start_date=database.get_earliest_entry_date(database_engine),
            default_end_date=date.today(),
            widget_key="summary_dates",
        )
    if start_date is None:
        return

    all_genders = database.get_all_genders(database_engine)
    with gender_column:
        chosen_gender_names = st.multiselect(
            "Genders", all_genders["gender_name"], default=list(all_genders["gender_name"]), key="summary_genders"
        )

    # --- Data ------------------------------------------------------------------
    entries_in_range = database.get_stock_entries(database_engine, start_date, end_date)
    if not entries_in_range.empty:
        entries_in_range = entries_in_range[entries_in_range["gender_name"].isin(chosen_gender_names)]

    if entries_in_range.empty:
        st.info("No entries for these dates and genders.")
        return

    showroom_names_in_order = list(database.get_all_showrooms(database_engine)["showroom_name"])
    summary_table = database.build_summary_table(entries_in_range, showroom_names_in_order)

    # --- Show the table ---------------------------------------------------------
    st.dataframe(summary_table, hide_index=True, width="stretch")
    st.caption(
        "Showroom columns = pieces allocated to that showroom. "
        "'Purchased but not yet allocated' is only correct if every purchase is entered, "
        "and if the purchase and its allocations fall inside the dates picked above."
    )

    # --- Excel download ----------------------------------------------------------
    excel_file_contents = create_excel_file(summary_table, make_entries_readable(entries_in_range))
    st.download_button(
        "Download as Excel",
        data=excel_file_contents,
        file_name=f"showroom_stock_summary_{start_date:%Y-%m-%d}_to_{end_date:%Y-%m-%d}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# ---------------------------------------------------------------------------
# Screen: History (everyone; editors can correct or delete)
# ---------------------------------------------------------------------------

def show_history_page(database_engine, access_level):
    st.title("History")
    show_saved_message_if_any()

    # --- Filters -------------------------------------------------------------
    first_row_column_1, first_row_column_2 = st.columns(2)
    with first_row_column_1:
        start_date, end_date = ask_for_date_range(
            "Dates",
            default_start_date=date.today() - timedelta(days=30),
            default_end_date=date.today(),
            widget_key="history_dates",
        )
    if start_date is None:
        return
    with first_row_column_2:
        chosen_entry_types = st.multiselect(
            "Type", database.ALL_ENTRY_TYPES, default=database.ALL_ENTRY_TYPES, key="history_types"
        )

    entries_in_range = database.get_stock_entries(database_engine, start_date, end_date)

    second_row_column_1, second_row_column_2, second_row_column_3 = st.columns(3)
    with second_row_column_1:
        all_genders = database.get_all_genders(database_engine)
        chosen_gender_name = st.selectbox(
            "Gender", all_genders["gender_name"], index=None, placeholder="All genders", key="history_gender"
        )
    with second_row_column_2:
        category_names_to_offer = []
        if chosen_gender_name:
            chosen_gender_id = int(
                all_genders.loc[all_genders["gender_name"] == chosen_gender_name, "gender_id"].iloc[0]
            )
            category_names_to_offer = database.get_categories_for_gender(database_engine, chosen_gender_id)[
                "category_name"
            ]
        chosen_category_name = st.selectbox(
            "Category",
            category_names_to_offer,
            index=None,
            placeholder="All categories" if chosen_gender_name else "Pick a gender first",
            key=f"history_category_{chosen_gender_name}",
        )
    with second_row_column_3:
        all_showrooms = database.get_all_showrooms(database_engine)
        chosen_showroom_name = st.selectbox(
            "Showroom", all_showrooms["showroom_name"], index=None, placeholder="All showrooms", key="history_showroom"
        )

    # --- Apply the filters ---------------------------------------------------
    filtered_entries = entries_in_range
    if not filtered_entries.empty:
        filtered_entries = filtered_entries[filtered_entries["entry_type"].isin(chosen_entry_types)]
        if chosen_gender_name:
            filtered_entries = filtered_entries[filtered_entries["gender_name"] == chosen_gender_name]
        if chosen_category_name:
            filtered_entries = filtered_entries[filtered_entries["category_name"] == chosen_category_name]
        if chosen_showroom_name:
            filtered_entries = filtered_entries[filtered_entries["showroom_name"] == chosen_showroom_name]

    if filtered_entries.empty:
        st.info("No entries match these filters.")
        return

    # Purchases and allocations are counted separately; adding them together
    # would count the same pieces twice.
    pieces_purchased = int(
        filtered_entries.loc[filtered_entries["entry_type"] == database.ENTRY_TYPE_PURCHASE, "quantity"].sum()
    )
    pieces_allocated = int(
        filtered_entries.loc[filtered_entries["entry_type"] == database.ENTRY_TYPE_ALLOCATION, "quantity"].sum()
    )
    st.caption(
        f"{len(filtered_entries)} entries · {pieces_purchased} pieces purchased · {pieces_allocated} pieces allocated"
    )
    st.dataframe(make_entries_readable(filtered_entries), hide_index=True, width="stretch")

    # --- Correct or delete (editors only) ------------------------------------
    if access_level == ACCESS_LEVEL_EDITOR:
        show_correct_or_delete_section(database_engine, filtered_entries)


def describe_entry_in_one_line(entry):
    """e.g. '#12 · 04/11/2026 · Allocation · Men · Jeans → Showroom A · 24 pcs'"""
    description = (
        f"#{entry['entry_id']} · {entry['entry_date']:%d/%m/%Y} · {entry['entry_type']} · "
        f"{entry['gender_name']} · {entry['category_name']}"
    )
    if entry["entry_type"] == database.ENTRY_TYPE_ALLOCATION:
        description += f" → {entry['showroom_name']}"
    description += f" · {entry['quantity']} pcs"
    return description


def show_correct_or_delete_section(database_engine, filtered_entries):
    """Let an editor pick one entry from the table above and change or delete it."""
    st.divider()
    st.subheader("Correct or delete an entry")

    entries_by_description = {
        describe_entry_in_one_line(entry): entry for _, entry in filtered_entries.iterrows()
    }
    chosen_description = st.selectbox(
        "Entry", list(entries_by_description.keys()), index=None, placeholder="Choose an entry", key="history_entry_to_fix"
    )
    if not chosen_description:
        return

    entry_to_fix = entries_by_description[chosen_description]
    entry_id = int(entry_to_fix["entry_id"])

    # Every box below is keyed by the entry number, so it starts filled in
    # with that entry's current values.
    column_1, column_2 = st.columns(2)
    with column_1:
        corrected_date = st.date_input(
            "Date", value=entry_to_fix["entry_date"], format="DD/MM/YYYY", key=f"fix_date_{entry_id}"
        )
        corrected_type = st.radio(
            "Type",
            database.ALL_ENTRY_TYPES,
            index=find_position_in_list(database.ALL_ENTRY_TYPES, entry_to_fix["entry_type"]),
            horizontal=True,
            key=f"fix_type_{entry_id}",
        )

        all_genders = database.get_all_genders(database_engine)
        corrected_gender_name = st.selectbox(
            "Gender",
            all_genders["gender_name"],
            index=find_position_in_list(all_genders["gender_name"], entry_to_fix["gender_name"]),
            key=f"fix_gender_{entry_id}",
        )
        corrected_gender_id = int(
            all_genders.loc[all_genders["gender_name"] == corrected_gender_name, "gender_id"].iloc[0]
        )

    with column_2:
        categories_for_gender = database.get_categories_for_gender(database_engine, corrected_gender_id)
        if categories_for_gender.empty:
            st.warning(f"{corrected_gender_name} has no categories yet. Add one on the Categories screen.")
            return
        corrected_category_name = st.selectbox(
            "Category",
            categories_for_gender["category_name"],
            index=find_position_in_list(categories_for_gender["category_name"], entry_to_fix["category_name"]),
            key=f"fix_category_{entry_id}_{corrected_gender_id}",
        )
        corrected_category_id = int(
            categories_for_gender.loc[
                categories_for_gender["category_name"] == corrected_category_name, "category_id"
            ].iloc[0]
        )

        corrected_showroom_id = None
        if corrected_type == database.ENTRY_TYPE_ALLOCATION:
            all_showrooms = database.get_all_showrooms(database_engine)
            corrected_showroom_name = st.selectbox(
                "Showroom",
                all_showrooms["showroom_name"],
                index=find_position_in_list(all_showrooms["showroom_name"], entry_to_fix["showroom_name"]),
                key=f"fix_showroom_{entry_id}",
            )
            corrected_showroom_id = int(
                all_showrooms.loc[all_showrooms["showroom_name"] == corrected_showroom_name, "showroom_id"].iloc[0]
            )

        corrected_quantity = st.number_input(
            "Quantity (pieces)", min_value=1, step=1, value=int(entry_to_fix["quantity"]), key=f"fix_quantity_{entry_id}"
        )
        corrected_note = st.text_input(
            "Note", value=entry_to_fix["note"] or "", key=f"fix_note_{entry_id}"
        )

    save_column, delete_column = st.columns(2)
    with save_column:
        if st.button("Save changes", type="primary", key=f"fix_save_{entry_id}"):
            database.update_stock_entry(
                database_engine,
                entry_id=entry_id,
                entry_date=corrected_date,
                entry_type=corrected_type,
                category_id=corrected_category_id,
                showroom_id=corrected_showroom_id,
                quantity=corrected_quantity,
                note=corrected_note,
            )
            remember_message_for_after_reload(f"Entry #{entry_id} updated.")
            st.session_state.pop("history_entry_to_fix", None)
            st.rerun()

    with delete_column:
        delete_is_confirmed = st.checkbox("Yes, I want to delete this entry", key=f"fix_confirm_delete_{entry_id}")
        if st.button("Delete entry", disabled=not delete_is_confirmed, key=f"fix_delete_{entry_id}"):
            database.delete_stock_entry(database_engine, entry_id)
            remember_message_for_after_reload(f"Entry #{entry_id} deleted.")
            st.session_state.pop("history_entry_to_fix", None)
            st.rerun()


# ---------------------------------------------------------------------------
# Screen: Categories (everyone; editors can add and rename)
# ---------------------------------------------------------------------------

def show_categories_page(database_engine, access_level):
    st.title("Categories")
    show_saved_message_if_any()

    all_genders = database.get_all_genders(database_engine)
    all_categories = database.get_all_categories_with_gender(database_engine)

    # --- List of categories, one tab per gender ------------------------------
    gender_tabs = st.tabs(list(all_genders["gender_name"]))
    for gender_tab, gender_name in zip(gender_tabs, all_genders["gender_name"]):
        with gender_tab:
            categories_for_this_gender = all_categories[all_categories["gender_name"] == gender_name]
            if categories_for_this_gender.empty:
                st.caption("No categories yet.")
            else:
                st.dataframe(
                    categories_for_this_gender[["category_name"]].rename(columns={"category_name": "Category"}),
                    hide_index=True,
                    width="stretch",
                )

    # --- List of showrooms -------------------------------------------------------
    with st.expander("Showrooms"):
        st.dataframe(
            database.get_all_showrooms(database_engine)[["showroom_name", "country"]].rename(
                columns={"showroom_name": "Showroom", "country": "Country"}
            ),
            hide_index=True,
            width="stretch",
        )

    if access_level != ACCESS_LEVEL_EDITOR:
        return

    # --- Editors only: add / rename ---------------------------------------------
    st.divider()
    add_column, rename_column = st.columns(2)

    with add_column:
        st.subheader("Add a category")
        gender_for_new_category = st.selectbox("Gender", all_genders["gender_name"], key="categories_page_new_gender")
        new_category_name = st.text_input("Category name", key="categories_page_new_category_name")
        if st.button("Add category"):
            gender_id = int(all_genders.loc[all_genders["gender_name"] == gender_for_new_category, "gender_id"].iloc[0])
            was_added, message, _ = database.add_category(database_engine, gender_id, new_category_name)
            if was_added:
                remember_message_for_after_reload(message)
                st.session_state.pop("categories_page_new_category_name", None)
                st.rerun()
            else:
                st.error(message)

    with rename_column:
        st.subheader("Rename a category")
        if all_categories.empty:
            st.caption("No categories yet.")
        else:
            categories_by_label = {
                f"{category['gender_name']} · {category['category_name']}": category
                for _, category in all_categories.iterrows()
            }
            chosen_label = st.selectbox(
                "Category", list(categories_by_label.keys()), index=None,
                placeholder="Choose a category", key="categories_page_rename_choice",
            )
            renamed_category_name = st.text_input("New name", key="categories_page_rename_new_name")
            if st.button("Rename"):
                if not chosen_label:
                    st.error("Please choose a category.")
                else:
                    category_to_rename = categories_by_label[chosen_label]
                    was_renamed, message = database.rename_category(
                        database_engine,
                        category_id=int(category_to_rename["category_id"]),
                        gender_id=int(category_to_rename["gender_id"]),
                        new_category_name=renamed_category_name,
                    )
                    if was_renamed:
                        remember_message_for_after_reload(message)
                        st.session_state.pop("categories_page_rename_new_name", None)
                        st.session_state.pop("categories_page_rename_choice", None)
                        st.rerun()
                    else:
                        st.error(message)

    st.divider()
    gender_column, showroom_column = st.columns(2)

    with gender_column:
        st.subheader("Add a gender")
        new_gender_name = st.text_input("Gender name", placeholder="e.g. Baby", key="categories_page_new_gender_name")
        if st.button("Add gender"):
            was_added, message = database.add_gender(database_engine, new_gender_name)
            if was_added:
                remember_message_for_after_reload(message)
                st.session_state.pop("categories_page_new_gender_name", None)
                st.rerun()
            else:
                st.error(message)

    with showroom_column:
        st.subheader("Add a showroom")
        new_showroom_name = st.text_input("Showroom name", key="categories_page_new_showroom_name")
        new_showroom_country = st.selectbox("Country", ["UAE", "Oman"], key="categories_page_new_showroom_country")
        if st.button("Add showroom"):
            was_added, message = database.add_showroom(database_engine, new_showroom_name, new_showroom_country)
            if was_added:
                remember_message_for_after_reload(message)
                st.session_state.pop("categories_page_new_showroom_name", None)
                st.rerun()
            else:
                st.error(message)


# ---------------------------------------------------------------------------
# Main: decide who is using the app, draw the side menu, show the right screen
# ---------------------------------------------------------------------------

def main():
    database_engine = get_database_engine()

    access_level = work_out_access_level()
    if access_level is None:
        show_login_page()
        return

    # --- Side menu -------------------------------------------------------------
    with st.sidebar:
        st.header("Showroom Stock Tracker")

        if access_level == ACCESS_LEVEL_EDITOR:
            available_pages = [PAGE_ADD_ENTRY, PAGE_SUMMARY, PAGE_HISTORY, PAGE_CATEGORIES]
        else:
            available_pages = [PAGE_SUMMARY, PAGE_HISTORY, PAGE_CATEGORIES]
        chosen_page = st.radio("Go to", available_pages, key="chosen_page")

        st.divider()
        if access_level == ACCESS_LEVEL_EDITOR:
            st.caption(f"Logged in as **{st.session_state['editor_name']}** (editor)")
            if st.button("Log out"):
                log_out()
        else:
            st.caption("Viewing only")
            with st.expander("Editor login"):
                show_editor_login_form()

    # --- Show the chosen screen ------------------------------------------------
    if chosen_page == PAGE_ADD_ENTRY:
        show_add_entry_page(database_engine, st.session_state["editor_name"])
    elif chosen_page == PAGE_SUMMARY:
        show_summary_page(database_engine)
    elif chosen_page == PAGE_HISTORY:
        show_history_page(database_engine, access_level)
    elif chosen_page == PAGE_CATEGORIES:
        show_categories_page(database_engine, access_level)


main()
