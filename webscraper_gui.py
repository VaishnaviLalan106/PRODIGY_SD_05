import requests
from bs4 import BeautifulSoup
import csv
import time
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from urllib.parse import urljoin
import re
import logging
from datetime import datetime

BASE_URL = "https://books.toscrape.com/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; Vaishnavi-Scraper/1.0; +https://books.toscrape.com/)"
}
POLITE_DELAY = 0.4  
LOG_FILE = "scraper.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler()  
    ]
)
logger = logging.getLogger("Task05Scraper")

RATING_MAP = {"One": 1, "Two": 2, "Three": 3, "Four": 4, "Five": 5}

def price_text_to_float(price_text):
    if not price_text:
        return None
    m = re.search(r"([0-9]+(?:\.[0-9]+)?)", price_text.replace(",", ""))
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            return None
    return None
def parse_product_item(product, base_url=BASE_URL):
    name = product.h3.a.get("title", "").strip()
    rel_link = product.h3.a.get("href", "")
    product_url = urljoin(base_url, rel_link)
    price_text = product.find("p", class_="price_color").text.strip() if product.find("p", class_="price_color") else ""
    price = price_text_to_float(price_text)
    star_tag = product.find("p", class_="star-rating")
    rating_word = star_tag.get("class", [None, None])[1] if star_tag else None
    rating = RATING_MAP.get(rating_word, None)
    avail_tag = product.find("p", class_="instock availability")
    availability = avail_tag.text.strip() if avail_tag else ""
    return {
        "name": name,
        "price_text": price_text,
        "price": price,
        "rating": rating,
        "availability": availability,
        "url": product_url
    }
def parse_product_detail(session, product_url):
    try:
        resp = session.get(product_url, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        logger.warning(f"Failed to fetch product page {product_url}: {e}")
        return {"upc": None, "description": None, "category": None}
    soup = BeautifulSoup(resp.text, "html.parser")
    upc = None
    table = soup.find("table", class_="table table-striped")
    if table:
        for row in table.find_all("tr"):
            header = row.th.text.strip() if row.th else ""
            if header == "UPC":
                upc = row.td.text.strip() if row.td else None
                break
    description = None
    desc_heading = soup.find("div", id="product_description")
    if desc_heading and desc_heading.find_next_sibling("p"):
        description = desc_heading.find_next_sibling("p").text.strip()
    category = None
    breadcrumb = soup.find("ul", class_="breadcrumb")
    if breadcrumb:
        items = breadcrumb.find_all("li")
        if len(items) >= 3:
            category = items[2].text.strip()
    return {"upc": upc, "description": description, "category": category}
def get_total_pages(soup):
    current = soup.find("li", class_="current")
    if current:
        text = current.text.strip()
        parts = text.split()
        if "of" in parts:
            try:
                total = int(parts[-1])
                return total
            except ValueError:
                return None
    return None
def scrape_all_books(output_csv_path, progress_cb=None, status_cb=None, stop_event=None):
    session = requests.Session()
    session.headers.update(HEADERS)
    logger.info("Starting scrape. Output CSV: %s", output_csv_path)
    if status_cb: status_cb("Starting scrape...")
    scraped_count = 0
    page_url = BASE_URL
    current_page = 1
    with open(output_csv_path, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow([
            "scrape_time_utc", "name", "price_text", "price", "rating",
            "availability", "product_url", "upc", "category", "description"
        ])
        try:
            resp = session.get(page_url, timeout=15)
            resp.raise_for_status()
        except Exception as e:
            logger.error("Failed to fetch the start page: %s", e)
            if status_cb: status_cb(f"Error fetching start page: {e}")
            raise
        soup = BeautifulSoup(resp.text, "html.parser")
        total_pages = get_total_pages(soup)
        logger.info("Discovered total pages: %s", total_pages if total_pages else "unknown")
        if status_cb:
            if total_pages:
                status_cb(f"Found {total_pages} pages. Starting scraping.")
            else:
                status_cb("Starting scraping (total pages unknown).")
        while True:
            if stop_event and stop_event.is_set():
                logger.info("Stop requested by user. Exiting loop.")
                if status_cb: status_cb("Stopping as requested...")
                break
            if current_page > 4:
                break
                try:
                    resp = session.get(page_url, timeout=15)
                    resp.raise_for_status()
                except Exception as e:
                    logger.warning("Failed to fetch page %s: %s", current_page, e)
                    if status_cb: status_cb(f"Failed to fetch page {current_page}: {e}")
                    break
                soup = BeautifulSoup(resp.text, "html.parser")
            logger.info("Parsing page %s", current_page)
            if status_cb: status_cb(f"Parsing page {current_page}...")
            product_cards = soup.find_all("article", class_="product_pod")
            for card in product_cards:
                info = parse_product_item(card, base_url=page_url)
                logger.debug("Parsed product summary: %s", info["name"])
                detail = parse_product_detail(session, info["url"])
                logger.debug("Parsed product detail for %s: UPC=%s", info["name"], detail.get("upc"))
                ts = datetime.utcnow().isoformat()
                writer.writerow([
                    ts,
                    info["name"],
                    info["price_text"],
                    info["price"],
                    info["rating"],
                    info["availability"],
                    info["url"],
                    detail.get("upc"),
                    detail.get("category"),
                    detail.get("description")
                ])
                csvfile.flush()
                scraped_count += 1
                if stop_event and stop_event.is_set():
                    break
                time.sleep(POLITE_DELAY)
            if progress_cb:
                progress_cb(current_page, total_pages)
            next_li = soup.find("li", class_="next")
            if next_li and next_li.a:
                next_href = next_li.a.get("href")
                page_url = urljoin(page_url, next_href)
                current_page += 1
                time.sleep(POLITE_DELAY)
                continue
            else:
                logger.info("No next page. Scraping finished.")
                break
    logger.info("Scraping completed. Products scraped: %d", scraped_count)
    if status_cb: status_cb(f"Completed: {scraped_count} products saved to {output_csv_path}")
    return scraped_count
class PolishedScraperGUI:
    def __init__(self, root):
        self.root = root
        root.title("Task-05 Web Scraper — Books (detailed)")
        root.geometry("720x380")
        root.resizable(False, False)
        padding = {"padx": 12, "pady": 6}
        top = ttk.Frame(root)
        top.pack(fill="x", **padding)
        ttk.Label(top, text="Save CSV as:").grid(row=0, column=0, sticky="w")
        self.file_var = tk.StringVar(value="books_full_output.csv")
        self.file_entry = ttk.Entry(top, textvariable=self.file_var, width=56)
        self.file_entry.grid(row=0, column=1, sticky="w", padx=(6,6))
        ttk.Button(top, text="Browse...", command=self.choose_file).grid(row=0, column=2, sticky="w")
        btn_frame = ttk.Frame(root)
        btn_frame.pack(fill="x", **padding)
        self.start_btn = ttk.Button(btn_frame, text="Start Scrape", command=self.start)
        self.start_btn.pack(side="left")
        self.cancel_btn = ttk.Button(btn_frame, text="Cancel", command=self.cancel, state="disabled")
        self.cancel_btn.pack(side="left", padx=(8,0))
        status_frame = ttk.Frame(root)
        status_frame.pack(fill="x", **padding)
        self.progress = ttk.Progressbar(status_frame, orient="horizontal", length=560, mode="determinate")
        self.progress.grid(row=0, column=0, columnspan=2, sticky="w")
        self.status_var = tk.StringVar(value="Idle. Press Start.")
        ttk.Label(status_frame, textvariable=self.status_var).grid(row=1, column=0, sticky="w", pady=(6,0))
        anim_frame = ttk.Frame(root)
        anim_frame.pack(fill="x", **padding)
        self.spinner_canvas = tk.Canvas(anim_frame, width=48, height=48, highlightthickness=0)
        self.spinner_canvas.pack(side="left")
        self.pulse_label = ttk.Label(anim_frame, text="Scraper", font=("Segoe UI", 14, "bold"))
        self.pulse_label.pack(side="left", padx=(8, 16))
        self.stats_var = tk.StringVar(value="Products scraped: 0")
        ttk.Label(root, textvariable=self.stats_var).pack(anchor="w", padx=12, pady=(4,0))
        self.worker = None
        self.stop_event = threading.Event()
        self.total_scraped = 0
        self.spinner_angle = 0
        self.pulse_state = 0
        self.animate()
    def choose_file(self):
        path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV files","*.csv")], initialfile=self.file_var.get())
        if path:
            self.file_var.set(path)
    def start(self):
        out_path = self.file_var.get().strip()
        if not out_path:
            messagebox.showwarning("Choose file", "Please choose a filename to save the CSV.")
            return
        self.start_btn.config(state="disabled")
        self.cancel_btn.config(state="normal")
        self.total_scraped = 0
        self.stats_var.set("Products scraped: 0")
        self.progress['value'] = 0
        self.progress['maximum'] = 1
        self.progress.config(mode="determinate")
        self.status_var.set("Initializing...")
        self.stop_event.clear()
        def worker_thread():
            try:
                count = scrape_all_books(
                    output_csv_path=out_path,
                    progress_cb=self.progress_callback,
                    status_cb=self.status_callback,
                    stop_event=self.stop_event
                )
                self.total_scraped = count
                if not self.stop_event.is_set():
                    self.status_callback(f"Completed: {count} products saved to {out_path}")
                else:
                    self.status_callback(f"Stopped by user. {count} products saved to {out_path}")
            except Exception as e:
                logger.exception("Exception in worker thread")
                self.status_callback(f"Error: {e}")
            finally:
                self.root.after(0, self.finish_ui)
        self.worker = threading.Thread(target=worker_thread, daemon=True)
        self.worker.start()
    def cancel(self):
        if messagebox.askyesno("Cancel", "Stop scraping?"):
            self.stop_event.set()
            self.cancel_btn.config(state="disabled")
            self.status_var.set("Stopping...")
    def progress_callback(self, current_page, total_pages):
        def gui():
            if total_pages:
                self.progress.config(mode="determinate", maximum=total_pages)
                self.progress['value'] = current_page
                self.status_var.set(f"Scraping page {current_page} of {total_pages}...")
            else:
                self.progress.config(mode="indeterminate")
                try:
                    self.progress.start(10)
                except Exception:
                    pass
                self.status_var.set(f"Scraping page {current_page} (total unknown)...")
        self.root.after(0, gui)

    def status_callback(self, text):
        logger.info("Status: %s", text)
        self.root.after(0, lambda: self.status_var.set(text))
        self.root.after(500, self.update_stats_from_csv)
    def update_stats_from_csv(self):
        path = self.file_var.get().strip()
        try:
            with open(path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            count = max(0, len(lines) - 1)
            self.total_scraped = count
            self.stats_var.set(f"Products scraped: {count}")
        except Exception:
            pass
    def finish_ui(self):
        self.start_btn.config(state="normal")
        self.cancel_btn.config(state="disabled")
        try:
            self.progress.stop()
        except Exception:
            pass
        if self.progress['mode'] == 'determinate' and self.progress['maximum'] != 0:
            self.progress['value'] = self.progress['maximum']
    def animate(self):
        self.spinner_canvas.delete("all")
        cx, cy, r = 24, 24, 18
        start = self.spinner_angle
        extent = 120 
        self.spinner_canvas.create_arc(cx-r, cy-r, cx+r, cy+r, start=start, extent=extent, style="arc", width=4)
        self.spinner_canvas.create_oval(cx-3, cy-3, cx+3, cy+3, fill="#444")
        self.spinner_angle = (self.spinner_angle + 12) % 360
        pulse_colors = ["#333333", "#444444", "#555555", "#666666", "#777777", "#666666", "#555555", "#444444"]
        color = pulse_colors[self.pulse_state % len(pulse_colors)]
        try:
            self.pulse_label.config(foreground=color)
        except Exception:
            pass
        self.pulse_state += 1
        self.root.after(80, self.animate)
def main():
    logger.info("Application started.")
    root = tk.Tk()
    app = PolishedScraperGUI(root)
    root.mainloop()
    logger.info("GUI mainloop ended. Application exiting.")
if __name__ == "__main__":
    main()
