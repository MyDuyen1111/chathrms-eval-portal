document.addEventListener("click", function (event) {
  // A link to a closed section opens it.
  var link = event.target.closest('a[href^="#"]');
  var section = link && document.querySelector(link.hash);
  if (section && section.tagName === "DETAILS") section.open = true;

  var cancel = event.target.closest("[data-close]");
  if (cancel) cancel.closest("details").open = false;

  // Copy buttons: data-copy holds the id of the element to copy.
  var button = event.target.closest("[data-copy]");
  if (!button) return;
  var text = document.getElementById(button.dataset.copy).textContent.trim();
  function done() {
    button.textContent = "Copied";
  }
  function fallback() {
    // navigator.clipboard needs HTTPS or localhost.
    var area = document.createElement("textarea");
    area.value = text;
    document.body.appendChild(area);
    area.select();
    document.execCommand("copy");
    area.remove();
    done();
  }
  if (navigator.clipboard) {
    navigator.clipboard.writeText(text).then(done, fallback);
  } else {
    fallback();
  }
});

// One click, one submit: reviews are append-only, so a second click on a slow save would record a second review.
document.addEventListener("submit", function (event) {
  var form = event.target;
  if (form.method !== "post") return;
  if (form.dataset.sent) {
    event.preventDefault();
    return;
  }
  form.dataset.sent = "1";
  var button = form.querySelector("button:not([type=button]), label.btn");
  if (!button) return;
  button.setAttribute("aria-busy", "true");
  if (button.dataset.busy) button.textContent = button.dataset.busy;
});

// A page restored by the Back button would still look busy.
window.addEventListener("pageshow", function (event) {
  if (event.persisted) location.reload();
});

// New run: show the name the run will get. The server still picks the real one, including any -r2.
function updateRunName() {
  var form = document.getElementById("new-run");
  if (!form) return;
  function tag(name) {
    var option = form.elements[name].selectedOptions[0];
    return (option && option.dataset.tag) || "?";
  }
  var type = form.elements.run_type.value;
  var dry = type === "Dry run";
  form.elements.milestone.disabled = dry;
  form.elements.quick_checks.disabled = dry;
  form.elements.quick_checks.required = !dry;
  var parts = [tag("product"), tag("set"), dry ? "dry" : tag("milestone"), tag("version"), tag("build")];
  document.getElementById("run-name").textContent = parts.join("-") + (type === "Rerun after fix" ? "-rN" : "");
}

// Review: Owner matters only on Fail, Failure type only when the owner is Bot.
function updateReview() {
  var form = document.getElementById("review-form");
  if (!form) return;
  var fail = form.elements.qc_result.value === "Fail";
  var bot = fail && form.elements.owner.value === "Bot";
  form.elements.owner.required = fail;
  form.elements.failure_type.required = bot;
  document.getElementById("owner-field").hidden = !fail;
  document.getElementById("type-field").hidden = !bot;
}

document.addEventListener("change", function (event) {
  var field = event.target;
  if (field.matches("[data-autosubmit]")) field.form.requestSubmit();
  if (field.matches("[data-reload]")) location.search = "?" + field.name + "=" + encodeURIComponent(field.value);
  updateRunName();
  updateReview();
});

updateRunName();
updateReview();

// Times are stored in UTC; show them in the viewer's own time.
document.querySelectorAll("time[data-local]").forEach(function (time) {
  time.textContent = new Date(time.dateTime).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
});

// Keep the open case in view in its list, and put the keyboard on the next thing to do, without scrolling the page.
var openRow = document.querySelector(".list .sel");
if (openRow) {
  var list = openRow.closest(".list");
  list.scrollTop += openRow.getBoundingClientRect().top - list.getBoundingClientRect().top - list.clientHeight / 2;
}
var firstTask = document.querySelector("[data-focus]");
if (firstTask) firstTask.focus({ preventScroll: true });

// Show password: the template hides the checkbox, so it appears only where this script runs.
document.querySelectorAll("[data-reveal]").forEach(function (box) {
  box.closest("label").hidden = false;
  box.addEventListener("change", function () {
    document.getElementById(box.dataset.reveal).type = box.checked ? "text" : "password";
  });
});
