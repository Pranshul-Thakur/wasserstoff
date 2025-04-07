import asyncio
import logging
from playwright.async_api import async_playwright
from dataclasses import dataclass
import json
import time
import random
import os
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@dataclass
class LinkedInProfile:
    name: str
    profile_url: str
    
class SimpleLinkedInScraper:
    def __init__(self, headless=True, cache_dir="profile_cache"):
        self.headless = headless
        self.profiles = []
        self.cache_dir = cache_dir
        self.visited_urls = set()
        self.action_count = {}
        self.MAX_REPEAT_ACTIONS = 10000
        
        if not os.path.exists(self.cache_dir):
            os.makedirs(self.cache_dir)
        
    async def login(self, page, email, password):
        try:
            await page.goto("https://www.linkedin.com/login")
            await page.fill("#username", email)
            await page.fill("#password", password)
            await page.click("button[type='submit']")
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=10000)
                await asyncio.sleep(5)
                login_success = False
                login_selectors = [
                    "div.feed-identity-module", 
                    "div.global-nav__me", 
                    "input[placeholder='Search']", 
                    "li.global-nav__primary-item", 
                    "div.search-results-container",
                    "header.global-nav__header",
                    "nav.global-nav"
                ]
                for selector in login_selectors:
                    try:
                        is_visible = await page.is_visible(selector, timeout=2000)
                        if is_visible:
                            login_success = True
                            break
                    except:
                        continue
                if login_success:
                    logger.info("Successfully logged in to LinkedIn")
                    await asyncio.sleep(3)
                    return True
                else:
                    current_url = page.url
                    if "login" not in current_url and "linkedin.com" in current_url:
                        logger.info("Login seems successful based on URL redirection")
                        await asyncio.sleep(3)
                        return True
                    logger.error("Could not confirm successful login")
                    return False
            except Exception as e:
                logger.error(f"Error checking login status: {str(e)}")
                current_url = page.url
                if "login" not in current_url and "linkedin.com" in current_url:
                    logger.info("Login seems successful based on URL despite error")
                    return True
                return False
        except Exception as e:
            logger.error(f"Login failed: {str(e)}")
            return False
    
    def get_cache_path(self, keyword):
        return os.path.join(self.cache_dir, f"{keyword.replace(' ', '_')}_profiles.json")
    
    def load_cached_profiles(self, keyword):
        cache_path = self.get_cache_path(keyword)
        if os.path.exists(cache_path):
            try:
                with open(cache_path, 'r') as f:
                    data = json.load(f)
                    cached_profiles = [LinkedInProfile(**p) for p in data.get('profiles', [])]
                    logger.info(f"Loaded {len(cached_profiles)} profiles from cache for '{keyword}'")
                    return cached_profiles
            except Exception as e:
                logger.error(f"Error loading cache: {str(e)}")
        return []
    
    def save_to_cache(self, keyword, profiles):
        cache_path = self.get_cache_path(keyword)
        with open(cache_path, 'w') as f:
            json.dump({
                "profiles": [
                    {
                        "name": p.name,
                        "profile_url": p.profile_url
                    } for p in profiles
                ],
                "timestamp": datetime.now().isoformat()
            }, f, indent=2)
        logger.info(f"Cached {len(profiles)} profiles for '{keyword}'")
    
    def track_action(self, action_name):
        if action_name == "scrape_profile":
            return
        if action_name not in self.action_count:
            self.action_count[action_name] = 1
        else:
            self.action_count[action_name] += 1
                
        if self.action_count[action_name] > self.MAX_REPEAT_ACTIONS:
            logger.warning(f"Many repetitions of action '{action_name}' detected ({self.action_count[action_name]} times). Continuing anyway.")
    
    async def search_profiles(self, page, keyword, max_pages=15):
        self.track_action(f"search_{keyword}")
        profile_urls = []
        try:
            await asyncio.sleep(random.uniform(1, 3))
            search_url = f"https://www.linkedin.com/search/results/people/?keywords={keyword.replace(' ', '%20')}"
            await page.goto(search_url)
            await page.wait_for_load_state("domcontentloaded")
            await asyncio.sleep(3)
            selectors = [
                "ul.reusable-search__entity-result-list", 
                "div.search-results-container", 
                "div.search-results",
                "div.search-results__cluster-content",
                "div[data-test-search-results-container]"
            ]
            
            found = False
            for selector in selectors:
                try:
                    is_visible = await page.is_visible(selector, timeout=3000)
                    if is_visible:
                        found = True
                        logger.info(f"Found search results with selector: {selector}")
                        break
                except:
                    continue          
            if not found:
                logger.warning(f"Could not find search results for '{keyword}'")
                all_list_items = await page.query_selector_all("li")
                if len(all_list_items) > 5:
                    logger.info(f"Found {len(all_list_items)} list items, assuming search results exist")
                    found = True
            
            if found:
                for current_page in range(1, max_pages + 1):
                    logger.info(f"Processing search page {current_page} for '{keyword}'")
                    await asyncio.sleep(random.uniform(2, 4))
                    profile_card_selectors = [
                        "li.reusable-search__result-container",
                        "li.search-result",
                        "div.entity-result",
                        "li.artdeco-list__item",
                        "li.reusable-search__entity-result-container",
                        "li[data-chameleon-result-urn]",
                        "div.entity-result__item",
                        "div.search-entity",
                        "li[data-occludable-job-id]"
                    ]
                    profile_cards = []
                    for selector in profile_card_selectors:
                        try:
                            cards = await page.query_selector_all(selector)
                            if cards and len(cards) > 0:
                                profile_cards = cards
                                logger.info(f"Found {len(cards)} profile cards with selector: {selector}")
                                break
                        except Exception as e:
                            logger.debug(f"Error with selector {selector}: {str(e)}")
                            continue
                    if not profile_cards:
                        logger.info("No profile cards found with standard selectors, trying link extraction")
                        links = await page.query_selector_all("a")
                        for link in links:
                            try:
                                href = await link.get_attribute("href")
                                if href and "/in/" in href:
                                    profile_url = href.split("?")[0]
                                    if profile_url not in profile_urls:
                                        profile_urls.append(profile_url)
                                        logger.info(f"Found profile URL via fallback: {profile_url}")
                            except:
                                continue
                    else:
                        for card in profile_cards:
                            link_selectors = [
                                "span.entity-result__title-text a",
                                "a.app-aware-link",
                                "a[data-control-name='search_srp_result']",
                                "span.entity-result__title a",
                                "a.search-result__result-link",
                                "a.ember-view",
                                "div.entity-result__title-text a",
                                "a"
                            ]
                            
                            profile_link = None
                            for selector in link_selectors:
                                try:
                                    links = await card.query_selector_all(selector)
                                    for link in links:
                                        href = await link.get_attribute("href")
                                        if href and "/in/" in href:
                                            profile_link = link
                                            break
                                    if profile_link:
                                        break
                                except:
                                    continue
                            
                            if profile_link:
                                try:
                                    href = await profile_link.get_attribute("href")
                                    if href:
                                        profile_url = href.split("?")[0]
                                        if "/in/" in profile_url and profile_url not in profile_urls:
                                            profile_urls.append(profile_url)
                                            logger.info(f"Found profile URL: {profile_url}")
                                except Exception as e:
                                    logger.error(f"Error extracting URL: {str(e)}")
                    if len(profile_urls) >= 200:
                        logger.info(f"Reached target of 200 profile URLs for '{keyword}'")
                        break
                    next_button = None
                    next_button_selectors = [
                        "button[aria-label='Next']",
                        "button.artdeco-pagination__button--next",
                        "li.artdeco-pagination__button--next button",
                        "button.artdeco-pagination__button--next:not([disabled])",
                        "button.next",
                        "button[data-test-pagination-page-btn='next']"
                    ]
                    
                    for selector in next_button_selectors:
                        try:
                            button = await page.query_selector(selector)
                            if button:
                                is_disabled = await button.is_disabled() if button else True
                                if not is_disabled:
                                    next_button = button
                                    break
                        except:
                            continue
                    
                    if next_button:
                        try:
                            is_visible = await next_button.is_visible()
                            if is_visible:
                                await next_button.click()
                                await page.wait_for_load_state("domcontentloaded")
                                await asyncio.sleep(random.uniform(3, 5))
                                logger.info("Clicked next page button")
                            else:
                                logger.info("Next button found but not visible")
                                break
                        except Exception as e:
                            logger.error(f"Error clicking next button: {str(e)}")
                            break
                    else:
                        logger.info("No next button found, this is the last page")
                        break
            
            logger.info(f"Found {len(profile_urls)} profile URLs for '{keyword}'")
            return profile_urls
            
        except Exception as e:
            logger.error(f"Error searching for '{keyword}': {str(e)}")
            return profile_urls
    
    async def scrape_profile(self, page, profile_url):
        if profile_url in self.visited_urls:
            logger.info(f"Already visited {profile_url}, skipping")
            return None
        self.visited_urls.add(profile_url)
        try:
            logger.info(f"Visiting: {profile_url}")
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    await page.goto(profile_url, timeout=30000)
                    break
                except Exception as e:
                    if attempt < max_retries - 1:
                        logger.warning(f"Retry {attempt+1}/{max_retries} for {profile_url}: {str(e)}")
                        await asyncio.sleep(random.uniform(3, 6))
                    else:
                        logger.error(f"Failed to load {profile_url} after {max_retries} attempts")
                        return None
                        
            await page.wait_for_load_state("domcontentloaded")
            await asyncio.sleep(random.uniform(2, 4))
            name_selectors = [
                "h1.text-heading-xlarge", 
                "h1.inline", 
                "h1.pv-top-card-section__name",
                "h1.text-heading-large",
                "h1.top-card-layout__title",
                "h1.profile-topcard-person-entity__name",
                "h1",
            ]
            
            name = "Unknown"
            for selector in name_selectors:
                try:
                    element = await page.query_selector(selector)
                    if element:
                        text = await element.inner_text()
                        if text and len(text) > 1:
                            name = text.strip()
                            logger.info(f"Found name: {name}")
                            break
                except:
                    continue
            profile = LinkedInProfile(
                name=name,
                profile_url=profile_url
            )
            logger.info(f"Successfully scraped profile: {name}")
            await asyncio.sleep(random.uniform(1, 3))
            return profile
        except Exception as e:
            logger.error(f"Error scraping profile {profile_url}: {str(e)}")
            return None
    
    async def run(self, email, password, keywords, profiles_per_keyword=40):
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(
                headless=self.headless,
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--disable-features=IsolateOrigins,site-per-process',
                    '--disable-dev-shm-usage',
                    '--no-sandbox',
                    '--disable-setuid-sandbox'
                ]
            )
            context = await browser.new_context(
                viewport={"width": 1366, "height": 768},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.75 Safari/537.36"
            )
            context.set_default_timeout(60000)
            
            page = await context.new_page()
            
            if not await self.login(page, email, password):
                logger.error("Failed to log in. Exiting.")
                await browser.close()
                return
            
            total_scraped = 0
            
            for keyword in keywords:
                logger.info(f"Processing keyword: {keyword}")
                
                cached_profiles = self.load_cached_profiles(keyword)
                if cached_profiles:
                    logger.info(f"Using {len(cached_profiles)} cached profiles for '{keyword}'")
                    self.profiles.extend(cached_profiles)
                    total_scraped += len(cached_profiles)
                    continue
                keyword_profiles = []
                profile_urls = await self.search_profiles(page, keyword)
                remaining_profiles = min(len(profile_urls), profiles_per_keyword)
                profile_urls = profile_urls[:remaining_profiles]
                batch_size = 10
                for i in range(0, len(profile_urls), batch_size):
                    batch_urls = profile_urls[i:i+batch_size]
                    batch_profiles = []
                    
                    for url in batch_urls:
                        try:
                            profile = await self.scrape_profile(page, url)
                            if profile:
                                keyword_profiles.append(profile)
                                batch_profiles.append(profile)
                                self.profiles.append(profile)
                                total_scraped += 1
                                logger.info(f"Successfully scraped: {profile.name} ({total_scraped} total)")
                                
                                if total_scraped >= 200:
                                    logger.info(f"Reached target of 200 profiles. Stopping.")
                                    break
                        except Exception as e:
                            logger.error(f"Error processing profile URL {url}: {str(e)}")
                        await asyncio.sleep(random.uniform(2, 5))
                    if batch_profiles:
                        self.save_to_cache(f"{keyword}_batch_{i//batch_size}", batch_profiles)
                        self.save_to_cache(keyword, keyword_profiles)
                    self.save_profiles(f"linkedin_profiles_progress_{total_scraped}.json")
                if total_scraped >= 200:
                    break
            await browser.close()
            logger.info(f"Scraping complete. Total profiles: {len(self.profiles)}")
    
    def save_profiles(self, filename="linkedin_profiles.json"):
        with open(filename, 'w') as f:
            json.dump({
                "profiles": [
                    {
                        "name": p.name,
                        "profile_url": p.profile_url
                    } for p in self.profiles
                ],
                "total": len(self.profiles),
                "timestamp": datetime.now().isoformat()
            }, f, indent=2)
        logger.info(f"Saved {len(self.profiles)} profiles to {filename}")

async def main():
    email = "pranshulthakur.11@gmail.com"
    password = "P@9356308775"
    keywords = ["software developer", "data analyst", "product manager", "machine learning engineer", "data scientist"]
    scraper = SimpleLinkedInScraper(headless=False)
    await scraper.run(email, password, keywords, profiles_per_keyword=40)
    scraper.save_profiles()
    print(f"Successfully scraped {len(scraper.profiles)} LinkedIn profiles!")
    print(f"Results saved to linkedin_profiles.json")
    
if __name__ == "__main__":
    asyncio.run(main())