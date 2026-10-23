"""CSV writer for reports."""
import csv
from pathlib import Path
from typing import List, Dict, Any
import aiofiles

from src.core.settings import get_settings


class CSVWriter:
    """Async CSV writer for crawl reports."""
    
    def __init__(self):
        self.settings = get_settings()
    
    async def write_report(self, job_id: str, domain: str, 
                           records: List[Dict[str, Any]], 
                           filename: str) -> Path:
        """Write records to CSV file."""
        # Ensure directory exists
        report_dir = self.settings.analyses_dir / domain
        report_dir.mkdir(parents=True, exist_ok=True)
        
        file_path = report_dir / filename
        
        if not records:
            # Write empty file with headers
            async with aiofiles.open(file_path, 'w', newline='', encoding='utf-8') as f:
                pass
            return file_path
        
        # Get headers from first record
        headers = list(records[0].keys())
        
        async with aiofiles.open(file_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(
                await f.__aenter__(),
                fieldnames=headers,
                extrasaction='ignore'
            )
            await f.write(','.join(headers) + '\n')
            
            for record in records:
                # Convert values to strings
                row = {k: str(v) if v is not None else '' for k, v in record.items()}
                line = ','.join(f'"{str(row[h]).replace(chr(34), chr(34)+chr(34))}"' for h in headers)
                await f.write(line + '\n')
        
        return file_path
    
    async def write_urls_csv(self, job_id: str, domain: str, 
                             urls: List[Dict]) -> Path:
        """Write URLs report."""
        return await self.write_report(job_id, domain, urls, "urls.csv")
    
    async def write_failed_urls_csv(self, job_id: str, domain: str,
                                    failed_urls: List[Dict]) -> Path:
        """Write failed URLs report."""
        return await self.write_report(job_id, domain, failed_urls, "failed_urls.csv")
    
    async def write_assets_csv(self, job_id: str, domain: str,
                               assets: List[Dict]) -> Path:
        """Write assets report."""
        return await self.write_report(job_id, domain, assets, "assets_status.csv")
    
    async def write_combined_report(self, job_id: str, domain: str,
                                    records: List[Dict]) -> Path:
        """Write combined report."""
        return await self.write_report(job_id, domain, records, "combine_report.csv")
    
    async def append_to_csv(self, file_path: Path, record: Dict) -> None:
        """Append single record to existing CSV."""
        file_exists = file_path.exists()
        
        async with aiofiles.open(file_path, 'a', newline='', encoding='utf-8') as f:
            if not file_exists:
                # Write header
                headers = list(record.keys())
                await f.write(','.join(headers) + '\n')
            
            headers = list(record.keys())
            line = ','.join(f'"{str(record.get(h, "")).replace(chr(34), chr(34)+chr(34))}"' for h in headers)
            await f.write(line + '\n')
    
    async def read_csv(self, file_path: Path) -> List[Dict[str, Any]]:
        """Read CSV file."""
        if not file_path.exists():
            return []
        
        records = []
        async with aiofiles.open(file_path, 'r', encoding='utf-8') as f:
            content = await f.read()
            
        lines = content.strip().split('\n')
        if not lines:
            return []
        
        reader = csv.DictReader(lines)
        for row in reader:
            records.append(dict(row))
        
        return records
