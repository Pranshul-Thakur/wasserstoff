import asyncio
import logging
import random
from typing import List, Dict, Any, Tuple
import json
import os
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta

from playwright.async_api import async_playwright, Browser, BrowserContext, Page

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("linkedin_advanced.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

@dataclass
class LinkedInProfile:
    name: str
    profile_url: str
    headline: str = ""
    location: str = ""
    connections: str = ""
    about: str = ""
    experience: List[Dict[str, str]] = None
    education: List[Dict[str, str]] = None
    scraped_at: str = ""
    
    def __post_init__(self):
        if self.experience is None:
            self.experience = []
        if self.education is None:
            self.education = []
        if not self.scraped_at:
            self.scraped_at = datetime.now().isoformat()

class AdvancedLinkedInScraper:
    def __init__(self, 
                 headless: bool = True, 
                 cache_dir: str = "cache",
                 max_retries: int = 3,
                 retry_delay: int = 60,
                 max_parallelism: int = 2):
        self.headless = headless
        self.cache_dir = cache_dir
        self.profiles_file = os.path.join(cache_dir, "profiles.json")
        self.state_file = os.path.join(cache_dir, "scraper_state.json")
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.max_parallelism = max_parallelism
        
        # Create cache directory if it doesn't exist
        os.makedirs(cache_dir, exist_ok=True)
        
        # Initialize state
        self.profiles = self._load_profiles()
        self.state = self._load_state()
        self.visited_urls = set(self.state.get("visited_urls", []))
        self.failed_urls = self.state.get("failed_urls", {})
        
        # Initialize counters
        self.target_profiles = 200
        self.total_requests = 0
        self.rate_limit_hits = 0
        self.start_time = datetime.now()
    
    def _load_profiles(self) -> List[LinkedInProfile]:
        """Load profiles from cache file."""
        if os.path.exists(self.profiles_file):
            try:
                with open(self.profiles_file, 'r') as f:
                    data = json.load(f)
                    return [LinkedInProfile(**p) for p in data.get("profiles", [])]
            except Exception as e:
                logger.error(f"Error loading profiles: {str(e)}")
        return []
    
    def _save_profiles(self) -> None:
        """Save profiles to cache file."""
        with open(self.profiles_file, 'w') as f:
            json.dump({"profiles": [asdict(p) for p in self.profiles]}, f, indent=2)
        logger.info(f"Saved {len(self.profiles)} profiles to cache")
    
    def _load_state(self) -> Dict[str, Any]:
        """Load scraper state from file."""
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading state: {str(e)}")
        return {
            "visited_urls": [],
            "failed_urls": {},
            "last_run": None,
            "keywords_progress": {}
        }
    
    def _save_state(self) -> None:
        """Save scraper state to file."""
        self.state["visited_urls"] = list(self.visited_urls)
        self.state["failed_urls"] = self.failed_urls
        self.state["last_run"] = datetime.now().isoformat()
        
        with open(self.state_file, 'w') as f:
            json.dump(self.state, f, indent=2)
        logger.info(f"Saved scraper state with {len(self.visited_urls)} visited URLs")
    
    async def create_browser_context(self) -> Tuple[Browser, BrowserContext, Page]:
        """Create a new browser context with randomized settings to avoid detection."""
        playwright = await async_playwright().start()
        
        # Random user agent from a list of common ones
        user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Safari/605.1.15",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:89.0) Gecko/20100101 Firefox/89.0"
        ]
        
        browser = await playwright.chromium.launch(headless=self.headless)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=random.choice(user_agents)
        )
        
        # Set random geolocation to avoid detection patterns
        # Using common locations in the US
        geolocation = random.choice([
            {"latitude": 37.7749, "longitude": -122.4194},  # San Francisco
            {"latitude": 40.7128, "longitude": -74.0060},   # New York
            {"latitude": 47.6062, "longitude": -122.3321}   # Seattle
        ])
        await context.set_geolocation(geolocation)
        
        # Add some browser fingerprint randomization
        await context.add_init_script("""
            // Override some navigator properties to add randomization
            const originalGetUserAgent = navigator.__proto__.userAgent;
            Object.defineProperty(navigator.__proto__, 'userAgent', {
                get: () => originalGetUserAgent,
            });
            
            // Add some random values for plugins length
            Object.defineProperty(navigator, 'plugins', {
                get: () => {
                    return { length: Math.floor(Math.random() * 5) + 1 };
                }
            });
        """)
        
        page = await context.new_page()
        page.set_default_timeout(30000)
        
        # Setup request interception to handle rate limiting
        async def handle_response(response):
            self.total_requests += 1
            if response.status in [429, 403]:
                self.rate_limit_hits += 1
                logger.warning(f"Rate limit detected: {response.status} on {response.url}")
        
        page.on("response", handle_response)
        
        return browser, context, page
    
    async def login(self, page: Page, email: str, password: str) -> bool:
        """Login to LinkedIn with retry logic."""
        for attempt in range(self.max_retries):
            try:
                await page.goto("https://www.linkedin.com/login")
                await page.fill("#username", email)
                await page.fill("#password", password)
                await page.click("button[type='submit']")
                
                # Wait for navigation after login
                await page.wait_for_selector("div[data-test-id='nav-search-typeahead']", timeout=10000)
                logger.info("Successfully logged in to LinkedIn")
                return True
            except Exception as e:
                logger.warning(f"Login attempt {attempt+1} failed: {str(e)}")
                if attempt < self.max_retries - 1:
                    # Add random delay before retrying
                    delay = self.retry_delay * (attempt + 1) * random.uniform(0.8, 1.2)
                    logger.info(f"Retrying login in {delay:.1f} seconds")
                    await asyncio.sleep(delay)
                    
                    # Refresh the page before retrying
                    try:
                        await page.reload()
                    except:
                        pass
        
        logger.error(f"Login failed after {self.max_retries} attempts")
        return False
    
    async def search_and_collect_profiles(self, page: Page, keyword: str, max_pages: int = 10) -> List[str]:
        """Search LinkedIn for profiles and collect profile URLs."""
        profile_urls = []
        keyword_progress = self.state.get("keywords_progress", {}).get(keyword, {})
        current_page = keyword_progress.get("current_page", 1)
        
        try:
            # Encode spaces as %20 for the URL
            search_url = f"https://www.linkedin.com/search/results/people/?keywords={keyword.replace(' ', '%20')}"
            if current_page > 1:
                search_url += f"&page={current_page}"
            
            logger.info(f"Searching for '{keyword}' - starting at page {current_page}")
            await page.goto(search_url)
            
            # Wait for search results to load
            await page.wait_for_selector("ul.reusable-search__entity-result-list", timeout=10000)
            
            while current_page <= max_pages:
                logger.info(f"Processing search results page {current_page} for keyword '{keyword}'")
                
                # Extract profile URLs from search results
                profile_cards = await page.query_selector_all("li.reusable-search__result-container")
                
                for card in profile_cards:
                    try:
                        profile_link = await card.query_selector("span.entity-result__title-text a")
                        if profile_link:
                            href = await profile_link.get_attribute("href")
                            if href:
                                # Clean the URL to remove tracking parameters
                                profile_url = href.split("?")[0]
                                if profile_url not in self.visited_urls:
                                    profile_urls.append(profile_url)
                    except Exception as e:
                        logger.error(f"Error extracting profile URL from card: {str(e)}")
                
                # Update progress in state
                if "keywords_progress" not in self.state:
                    self.state["keywords_progress"] = {}
                self.state["keywords_progress"][keyword] = {"current_page": current_page}
                
                # Check if there's a next page
                next_button = await page.query_selector("button[aria-label='Next']")
                if next_button and not await next_button.is_disabled():
                    current_page += 1
                    await next_button.click()
                    # Wait for next page to load
                    await page.wait_for_load_state("networkidle")
                    # Add random delay to avoid detection
                    await asyncio.sleep(random.uniform(3, 7))
                else:
                    logger.info(f"No more pages of search results for '{keyword}'")
                    break
                
            return profile_urls
            
        except Exception as e:
            logger.error(f"Error during search for '{keyword}': {str(e)}")
            return profile_urls
    
    async def scrape_profile(self, page: Page, profile_url: str) -> LinkedInProfile:
        """Scrape a LinkedIn profile page."""
        try:
            if profile_url in self.visited_urls:
                logger.info(f"Skipping already visited profile: {profile_url}")
                return None
            
            # Check if this URL has failed too many times
            if profile_url in self.failed_urls and self.failed_urls[profile_url] >= self.max_retries:
                logger.info(f"Skipping previously failed profile: {profile_url}")
                return None
            
            logger.info(f"Visiting profile: {profile_url}")
            
            # Navigate to the profile
            response = await page.goto(profile_url)
            if response.status >= 400:
                logger.warning(f"Error accessing profile {profile_url}: HTTP {response.status}")
                self.failed_urls[profile_url] = self.failed_urls.get(profile_url, 0) + 1
                return None
            
            await page.wait_for_load_state("domcontentloaded")
            
            # Check for challenge or login page
            if await page.query_selector("form#challenge-form") or await page.query_selector("#login-form"):
                logger.warning("Detected security challenge or login redirect")
                self.failed_urls[profile_url] = self.failed_urls.get(profile_url, 0) + 1
                return None
            
            # Extract profile information
            profile = LinkedInProfile(
                name="Unknown",
                profile_url=profile_url,
                scraped_at=datetime.now().isoformat()
            )
            
            # Extract name (with multiple possible selectors)
            for selector in ["h1.text-heading-xlarge", "h1.inline", "h1.pv-top-card-section__name"]:
                name_element = await page.query_selector(selector)
                if name_element:
                    profile.name = await name_element.inner_text()
                    break
            
            # Extract headline
            headline_selectors = [
                "div.text-body-medium", 
                "h2.mt1", 
                "h2.pv-top-card-section__headline"
            ]
            for selector in headline_selectors:
                element = await page.query_selector(selector)
                if element:
                    profile.headline = await element.inner_text()
                    break
            
            # Extract location
            location_selectors = [
                "span.text-body-small:has-text('Location')",
                "li.pv-top-card-v2-section__location",
                "span.pv-top-card-section__location"
            ]
            for selector in location_selectors:
                element = await page.query_selector(selector)
                if element:
                    profile.location = await element.inner_text()
                    break
            
            # Mark URL as visited
            self.visited_urls.add(profile_url)
            
            # Clean up the extracted data
            profile.name = profile.name.strip()
            profile.headline = profile.headline.strip()
            profile.location = profile.location.strip()
            
            return profile
            
        except Exception as e:
            logger.error(f"Error scraping profile {profile_url}: {str(e)}")
            self.failed_urls[profile_url] = self.failed_urls.get(profile_url, 0) + 1
            return None
    
    async def process_profile_batch(self, email: str, password: str, profile_urls: List[str]) -> List[LinkedInProfile]:
        """Process a batch of profile URLs with a single browser instance."""
        browser, context, page = await self.create_browser_context()
        profiles = []
        
        try:
            login_success = await self.login(page, email, password)
            if not login_success:
                return profiles
            
            for url in profile_urls:
                # Check if we've already collected enough profiles
                if len(self.profiles) >= self.target_profiles:
                    break
                    
                # Add randomized delay between profile visits
                await asyncio.sleep(random.uniform(2, 5))
                
                profile = await self.scrape_profile(page, url)
                if profile:
                    profiles.append(profile)
                    
                    # Save progress periodically
                    if len(profiles) % 5 == 0:
                        self._save_state()
            
            return profiles
            
        except Exception as e:
            logger.error(f"Error processing profile batch: {str(e)}")
            return profiles
        finally:
            # Close the browser
            await browser.close()
    
    async def run_parallel(self, email: str, password: str, keywords: List[str], max_pages_per_keyword: int = 10) -> None:
        """Run the scraper with parallel processing."""
        try:
            logger.info(f"Starting scraper run with {len(keywords)} keywords")
            self.start_time = datetime.now()
            
            # Create a browser for searching
            browser, context, page = await self.create_browser_context()
            
            try:
                # Login
                login_success = await self.login(page, email, password)
                if not login_success:
                    return
                
                # Start with profiles already in cache
                if self.profiles:
                    logger.info(f"Starting with {len(self.profiles)} profiles from cache")
                
                # Process each keyword to collect profile URLs
                all_profile_urls = []
                for keyword in keywords:
                    if len(self.profiles) >= self.target_profiles:
                        logger.info(f"Already collected {len(self.profiles)} profiles. Target reached.")
                        break
                    
                    profile_urls = await self.search_and_collect_profiles(
                        page, keyword, max_pages=max_pages_per_keyword)
                    
                    logger.info(f"Found {len(profile_urls)} new profile URLs for keyword '{keyword}'")
                    all_profile_urls.extend(profile_urls)
                    
                    # Save state after each keyword
                    self._save_state()
                    
                    # Add random delay between keywords
                    await asyncio.sleep(random.uniform(5, 10))
                
                # Filter out already visited URLs
                all_profile_urls = [url for url in all_profile_urls if url not in self.visited_urls]
                logger.info(f"Found {len(all_profile_urls)} new unique profile URLs across all keywords")
                
            finally:
                # Close the search browser
                await browser.close()
            
            # If we already have enough profiles, we're done
            if len(self.profiles) >= self.target_profiles:
                logger.info(f"Already collected {len(self.profiles)} profiles. Target reached.")
                return
            
            # Process profile URLs in parallel batches
            remaining_urls = all_profile_urls.copy()
            while remaining_urls and len(self.profiles) < self.target_profiles:
                # Determine batch size based on remaining profiles needed
                profiles_needed = self.target_profiles - len(self.profiles)
                batch_size = min(profiles_needed, 20)  # Process up to 20 profiles per batch
                
                # Create batches with a maximum of max_parallelism concurrent browsers
                batches = []
                for i in range(0, min(len(remaining_urls), batch_size), self.max_parallelism):
                    batch = remaining_urls[i:i + self.max_parallelism]
                    batches.append(batch)
                
                for batch in batches:
                    if len(self.profiles) >= self.target_profiles:
                        break
                    
                    # Process this batch in parallel
                    tasks = []
                    for i in range(0, len(batch), max(1, len(batch) // self.max_parallelism)):
                        sub_batch = batch[i:i + max(1, len(batch) // self.max_parallelism)]
                        tasks.append(self.process_profile_batch(email, password, sub_batch))
                    
                    results = await asyncio.gather(*tasks)
                    new_profiles = [p for result in results for p in result if p]
                    
                    # Add new profiles to our collection
                    self.profiles.extend(new_profiles)
                    logger.info(f"Added {len(new_profiles)} new profiles. Total: {len(self.profiles)}")
                    
                    # Save progress
                    self._save_profiles()
                    self._save_state()
                    
                    # Remove processed URLs from remaining list
                    for url_batch in batch:
                        if url_batch in remaining_urls:
                            remaining_urls.remove(url_batch)
                    
                    # Add delay between batches to avoid rate limiting
                    await asyncio.sleep(random.uniform(10, 15))
            
            # Final save
            self._save_profiles()
            self._save_state()
            
            # Log statistics
            duration = datetime.now() - self.start_time
            logger.info(f"Scraper run completed in {duration}")
            logger.info(f"Collected {len(self.profiles)} profiles")
            logger.info(f"Total requests: {self.total_requests}")
            logger.info(f"Rate limit hits: {self.rate_limit_hits}")
            
        except Exception as e:
            logger.error(f"Error during parallel run: {str(e)}")
    
    def export_profiles_json(self, output_file: str = "linkedin_profiles.json") -> None:
        """Export collected profiles to a JSON file."""
        with open(output_file, 'w') as f:
            json.dump({"profiles": [asdict(p) for p in self.profiles]}, f, indent=2)
        logger.info(f"Exported {len(self.profiles)} profiles to {output_file}")
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get statistics about the scraper run."""
        return {
            "total_profiles": len(self.profiles),
            "visited_urls": len(self.visited_urls),
            "failed_urls": len(self.failed_urls),
            "total_requests": self.total_requests,
            "rate_limit_hits": self.rate_limit_hits,
            "start_time": self.start_time.isoformat() if hasattr(self, 'start_time') else None,
            "duration": str(datetime.now() - self.start_time) if hasattr(self, 'start_time') else None
        }

# Example usage
async def main():
    # Configuration
    email = "your_linkedin_email@example.com"
    password = "your_linkedin_password"
    keywords = ["software engineer", "data scientist", "product manager", "software developer", "python developer"]
    
    # Initialize the scraper
    scraper = AdvancedLinkedInScraper(
        headless=True,  # Set to False to see the browser
        max_parallelism=2  # Number of concurrent browsers
    )
    
    # Run the scraper
    await scraper.run_parallel(email, password, keywords, max_pages_per_keyword=5)
    
    # Export the results
    scraper.export_profiles_json()
    
    # Print statistics
    print(scraper.get_statistics())

if __name__ == "__main__":
    asyncio.run(main())