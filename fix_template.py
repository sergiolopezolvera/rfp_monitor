import re

with open("app/web/templates/opportunities.html") as f:
    content = f.read()

# Replace the two forms with a single unified form
old_forms_regex = r"<form method=\"get\" action=\"/opportunities\" class=\"toolbar\">.*?</form>\s*<form method=\"get\" action=\"/opportunities/export\" class=\"export-toolbar\">.*?</form>"

new_form = """<form method="get" action="/opportunities" class="toolbar" style="flex-wrap: wrap; gap: 1rem;">
      <div style="display: flex; gap: 0.5rem; flex-wrap: wrap; align-items: center; width: 100%;">
        <select name="source">
          <option value="">All sources</option>
          {% for source_name in filters.sources %}
            <option value="{{ source_name }}" {% if current_filters.source == source_name %}selected{% endif %}>{{ source_name }}</option>
          {% endfor %}
        </select>

        <select name="status">
          <option value="">All statuses</option>
          {% for status in filters.statuses %}
            <option value="{{ status }}" {% if current_filters.status == status %}selected{% endif %}>{{ status }}</option>
          {% endfor %}
        </select>

        <select name="fit_result" id="fit_result">
          <option value="">All fit results</option>
          <option value="fit" {% if current_filters.fit_result == "fit" %}selected{% endif %}>Fit</option>
          <option value="not_fit" {% if current_filters.fit_result == "not_fit" %}selected{% endif %}>Not fit</option>
          <option value="unanalyzed" {% if current_filters.fit_result == "unanalyzed" %}selected{% endif %}>Unanalyzed</option>
        </select>

        <select name="fit_level" id="fit_level" {% if current_filters.fit_result != "fit" %}disabled{% endif %}>
          <option value="">All fit levels</option>
          <option value="3" {% if current_filters.fit_level == "3" %}selected{% endif %}>High</option>
          <option value="2" {% if current_filters.fit_level == "2" %}selected{% endif %}>Medium</option>
          <option value="1" {% if current_filters.fit_level == "1" %}selected{% endif %}>Low</option>
        </select>
      </div>

      <div style="display: flex; gap: 0.5rem; flex-wrap: wrap; align-items: center; width: 100%;">
        <label>
          Scraped from
          <input id="export-created-from" type="date" name="created_from" value="{{ current_filters.created_from }}" />
        </label>
        <label>
          Scraped to
          <input id="export-created-to" type="date" name="created_to" value="{{ current_filters.created_to }}" />
        </label>
        <button
          type="button"
          class="secondary"
          id="export-this-week"
          data-week-start="{{ this_week.start }}"
          data-week-end="{{ this_week.end }}"
        >
          This week
        </button>

        <label style="margin-left: 1rem;">
          Closing after
          <input type="date" name="closing_after" value="{{ current_filters.closing_after }}" />
        </label>

        <div style="margin-left: auto; display: flex; gap: 0.5rem;">
          <button type="submit">Apply filters</button>
          <button type="submit" formaction="/opportunities/export" class="secondary">Export</button>
          <a href="/opportunities" class="badge">Reset</a>
        </div>
      </div>
    </form>"""

content = re.sub(old_forms_regex, new_form, content, flags=re.DOTALL)

# Add javascript to toggle the fit level dropdown
js_to_add = """
  <script>
    const fitResultSelect = document.getElementById("fit_result");
    const fitLevelSelect = document.getElementById("fit_level");

    if (fitResultSelect && fitLevelSelect) {
      fitResultSelect.addEventListener("change", (e) => {
        if (e.target.value === "fit") {
          fitLevelSelect.disabled = false;
        } else {
          fitLevelSelect.disabled = true;
          fitLevelSelect.value = "";
        }
      });
    }

    const thisWeekButton = document.getElementById("export-this-week");
    if (thisWeekButton) {
      thisWeekButton.addEventListener("click", () => {
        document.getElementById("export-created-from").value = thisWeekButton.dataset.weekStart;
        document.getElementById("export-created-to").value = thisWeekButton.dataset.weekEnd;
      });
    }
  </script>
"""

# Replace the old script block
old_script_block = """  <script>
    const thisWeekButton = document.getElementById("export-this-week");
    if (thisWeekButton) {
      thisWeekButton.addEventListener("click", () => {
        document.getElementById("export-created-from").value = thisWeekButton.dataset.weekStart;
        document.getElementById("export-created-to").value = thisWeekButton.dataset.weekEnd;
      });
    }
  </script>"""

content = content.replace(old_script_block, js_to_add)

# update pagination
old_pag_link1 = """?page={{ page_data.page - 1 }}&source={{ current_filters.source }}&status={{ current_filters.status }}&fit_result={{ current_filters.fit_result }}&closing_from={{ current_filters.closing_from }}&closing_to={{ current_filters.closing_to }}"""
new_pag_link1 = """?page={{ page_data.page - 1 }}&source={{ current_filters.source }}&status={{ current_filters.status }}&fit_result={{ current_filters.fit_result }}&fit_level={{ current_filters.fit_level }}&created_from={{ current_filters.created_from }}&created_to={{ current_filters.created_to }}&closing_after={{ current_filters.closing_after }}"""

old_pag_link2 = """?page={{ page_data.page + 1 }}&source={{ current_filters.source }}&status={{ current_filters.status }}&fit_result={{ current_filters.fit_result }}&closing_from={{ current_filters.closing_from }}&closing_to={{ current_filters.closing_to }}"""
new_pag_link2 = """?page={{ page_data.page + 1 }}&source={{ current_filters.source }}&status={{ current_filters.status }}&fit_result={{ current_filters.fit_result }}&fit_level={{ current_filters.fit_level }}&created_from={{ current_filters.created_from }}&created_to={{ current_filters.created_to }}&closing_after={{ current_filters.closing_after }}"""

content = content.replace(old_pag_link1, new_pag_link1).replace(old_pag_link2, new_pag_link2)

with open("app/web/templates/opportunities.html", "w") as f:
    f.write(content)
