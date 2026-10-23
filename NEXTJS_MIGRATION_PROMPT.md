# V3 Crawler Platform - Next.js Migration Prompt

## Overview
Convert the existing Python-based V3 Crawler Platform (FastAPI + Jinja2 UI) to a modern Next.js application with a headless Python API backend. The current application serves both API and web UI through uvicorn, which needs to be separated into distinct frontend and backend services.

## Current Architecture Analysis

### Backend (Python/FastAPI)
- **Main API**: `src/api/main.py` - FastAPI application with CORS enabled
- **Routes**: 
  - `src/api/routes_crawl.py` - Crawl operations (start, stop, pause, resume, status)
  - `src/api/routes_reports.py` - Report generation and downloads
- **Core Components**:
  - `src/core/models.py` - Pydantic models (CrawlJobConfig, JobStatus, etc.)
  - `src/core/crawl_manager.py` - Async crawl management
  - `src/core/sync_crawl_manager.py` - Sync wrapper for UI
  - `src/core/settings.py` - Configuration management
- **Database**: MongoDB integration via `src/database/mongo_client.py`
- **Storage**: Filesystem-based storage in `data/` directory

### Frontend (Python/Jinja2)
- **UI App**: `src/ui/app.py` - FastAPI serving Jinja2 templates
- **Templates**: `src/ui/templates/` - HTML templates with basic styling
- **Current Routes**:
  - `/` - Configuration form for starting crawls
  - `/jobs` - Paginated job listing with filters
  - `/job/{job_id}` - Job details and progress view
  - `/job/{job_id}/analysis` - CSV analysis viewer
  - API endpoints: `/api/jobs`, `/api/job/{job_id}/status`

### Key Features to Preserve
1. **Job Management**: Start, stop, pause, resume, retry, delete jobs
2. **Real-time Progress**: Live status updates and progress tracking
3. **Comprehensive Configuration**: All current crawl settings and options
4. **Reporting**: CSV reports, asset statistics, failure analysis
5. **File Downloads**: Direct access to crawled content and reports
6. **Filtering & Pagination**: Job listing with domain, status, month filters

## Migration Requirements

### 1. Backend API Enhancement
**Objective**: Make the existing FastAPI backend production-ready for external consumption

#### Tasks:
- **Authentication & Security**:
  - Implement API key authentication or JWT tokens
  - Add rate limiting per client
  - Secure CORS configuration for specific domains
  - Input validation and sanitization

- **API Improvements**:
  - Add OpenAPI/Swagger documentation enhancements
  - Implement proper error handling with standardized error responses
  - Add request/response logging
  - Add health check endpoints with dependency status

- **Performance Optimizations**:
  - Implement response caching for static data
  - Add compression middleware
  - Optimize database queries with proper indexing
  - Add connection pooling

- **New Endpoints Needed**:
  ```python
  # Authentication
  POST /auth/login
  POST /auth/refresh
  DELETE /auth/logout
  
  # Enhanced job management
  GET /jobs/{job_id}/logs          # Real-time log streaming
  GET /jobs/{job_id}/preview        # Preview crawled content
  GET /jobs/{job_id}/download/*     # Secure file downloads
  
  # Statistics and analytics
  GET /stats/overview              # Platform statistics
  GET /stats/domains               # Domain-wise statistics
  GET /stats/performance           # Performance metrics
  
  # Configuration management
  GET /config/templates            # Saved configuration templates
  POST /config/templates           # Save new template
  ```

### 2. Next.js Frontend Application
**Objective**: Create a modern, responsive web interface that consumes the Python API

#### Technology Stack:
- **Framework**: Next.js 14+ with App Router
- **Styling**: Tailwind CSS + shadcn/ui components
- **State Management**: Zustand or React Query for server state
- **Real-time Updates**: WebSocket or Server-Sent Events
- **Forms**: React Hook Form + Zod validation
- **Charts**: Recharts for analytics visualization
- **File Handling**: Proper download handlers with progress tracking

#### Core Pages & Components:

**1. Dashboard (`/dashboard`)**
- Platform overview with key metrics
- Active jobs with real-time progress
- Recent activity feed
- Quick start crawl form
- Performance charts

**2. Job Management (`/jobs`)**
- Advanced filtering (domain, status, date range, tags)
- Sortable columns with pagination
- Bulk actions (pause, stop, delete multiple)
- Export job list to CSV
- Real-time status updates

**3. Job Details (`/jobs/[id]`)**
- Comprehensive job information
- Live progress bar with stage breakdown
- Real-time logs with filtering
- Asset download statistics
- Action buttons (pause, resume, stop, retry)
- Configuration preview

**4. Crawl Configuration (`/crawl/new`)**
- Multi-step form with validation
- Configuration templates (save/load)
- Real-time domain verification
- Preview of excluded/included URLs
- Advanced settings accordion

**5. Reports & Analytics (`/reports/[id]`)**
- Interactive data tables with sorting/filtering
- Chart visualizations for crawl statistics
- Asset breakdown by type
- Failure analysis with categorization
- Export options (CSV, PDF, JSON)

**6. Settings (`/settings`)**
- API configuration
- User preferences
- Notification settings
- Saved templates management

#### Key Features to Implement:

**Real-time Communication**:
```javascript
// WebSocket connection for live updates
const useWebSocket = (jobId) => {
  const [socket, setSocket] = useState(null);
  const [progress, setProgress] = useState(null);
  
  useEffect(() => {
    const ws = new WebSocket(`ws://localhost:8000/ws/jobs/${jobId}`);
    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      setProgress(data);
    };
    setSocket(ws);
    return () => ws.close();
  }, [jobId]);
  
  return { progress, socket };
};
```

**Advanced Form Handling**:
```typescript
// Crawl configuration form with validation
const crawlConfigSchema = z.object({
  domain: z.string().min(1, "Domain is required"),
  maxDepth: z.number().min(0).max(10),
  concurrentRequests: z.number().min(1).max(100),
  // ... all other fields
});

type CrawlConfig = z.infer<typeof crawlConfigSchema>;
```

**Data Fetching with React Query**:
```typescript
// API client with error handling
const useJobs = (filters: JobFilters) => {
  return useQuery({
    queryKey: ['jobs', filters],
    queryFn: () => fetchJobs(filters),
    staleTime: 30000,
    refetchInterval: 10000, // Refresh every 10 seconds
  });
};
```

### 3. Deployment & Infrastructure

#### Backend Deployment:
- **Containerization**: Dockerfile for Python API
- **Process Management**: Gunicorn with multiple workers
- **Load Balancing**: Nginx reverse proxy
- **Database**: MongoDB with proper indexing
- **Monitoring**: Prometheus + Grafana metrics
- **Logging**: Structured logging with ELK stack

#### Frontend Deployment:
- **Build Process**: Next.js production build optimization
- **Static Assets**: CDN integration for faster loading
- **Environment Variables**: Proper configuration management
- **SEO**: Meta tags and structured data

#### Development Environment:
```yaml
# docker-compose.yml for local development
version: '3.8'
services:
  mongodb:
    image: mongo:6
    ports:
      - "27017:27017"
    volumes:
      - mongodb_data:/data/db
  
  api:
    build: ./backend
    ports:
      - "8000:8000"
    depends_on:
      - mongodb
    environment:
      - MONGODB_URL=mongodb://mongodb:27017
      - NODE_ENV=development
  
  frontend:
    build: ./frontend
    ports:
      - "3000:3000"
    depends_on:
      - api
    environment:
      - NEXT_PUBLIC_API_URL=http://localhost:8000
```

### 4. Migration Strategy

#### Phase 1: Backend API Enhancement (Week 1-2)
1. Implement authentication middleware
2. Add new API endpoints
3. Enhance error handling and validation
4. Add comprehensive logging
5. Write API tests

#### Phase 2: Frontend Development (Week 3-4)
1. Set up Next.js project structure
2. Implement core pages and components
3. Add real-time communication
4. Create responsive design
5. Integrate with backend API

#### Phase 3: Integration & Testing (Week 5)
1. End-to-end testing
2. Performance optimization
3. Security audit
4. Documentation
5. User acceptance testing

#### Phase 4: Deployment (Week 6)
1. Set up production infrastructure
2. Migrate existing data
3. Configure monitoring
4. Go-live with fallback plan

### 5. API Contract Definition

#### Crawl Job Endpoints:
```typescript
// Start Crawl
POST /api/crawl/start
{
  domain: string;
  entry_url?: string;
  max_depth: number; // 0-10
  max_pages?: number;
  concurrent_requests: number; // 1-100
  // ... all other config options
}

// Response
{
  job_id: string;
  status: "pending" | "running" | "completed" | "failed";
  message: string;
  estimated_duration?: number;
}

// Get Job Status
GET /api/crawl/status/{job_id}
{
  job_id: string;
  status: JobStatus;
  stage: JobStage;
  progress_percent: number;
  pages_crawled: number;
  assets_downloaded: number;
  queue_remaining: number;
  failed_urls: number;
  elapsed_seconds: number;
  eta_seconds?: number;
  current_url?: string;
  message: string;
  metrics: {
    requests_per_second: number;
    success_rate: number;
    average_response_time: number;
  };
}

// List Jobs
GET /api/crawl/jobs?page=1&per_page=25&domain=example.com&status=running
{
  jobs: Job[];
  pagination: {
    page: number;
    per_page: number;
    total: number;
    total_pages: number;
  };
  filters: {
    domains: string[];
    statuses: JobStatus[];
    months: string[];
  };
}
```

### 6. Success Metrics

#### Performance Targets:
- Page load time: < 2 seconds
- API response time: < 500ms (95th percentile)
- Real-time update latency: < 100ms
- Concurrent users: 100+ simultaneous

#### Feature Completeness:
- [ ] All current features preserved
- [ ] Enhanced user experience
- [ ] Mobile responsive design
- [ ] Real-time updates working
- [ ] Comprehensive error handling
- [ ] Security measures implemented

### 7. Testing Strategy

#### Backend Testing:
- Unit tests for all API endpoints
- Integration tests with MongoDB
- Load testing for concurrent requests
- Security testing for authentication

#### Frontend Testing:
- Component unit tests with Jest
- Integration tests with Cypress
- User acceptance testing
- Performance testing with Lighthouse

### 8. Documentation Requirements

#### API Documentation:
- OpenAPI 3.0 specification
- Interactive API documentation (Swagger UI)
- Code examples in multiple languages
- Authentication and authorization guide

#### Frontend Documentation:
- Component library documentation
- User guide with screenshots
- Deployment instructions
- Troubleshooting guide

## Deliverables

1. **Enhanced Python API** with authentication and new endpoints
2. **Next.js Frontend Application** with modern UI/UX
3. **Docker Configuration** for containerized deployment
4. **Comprehensive Test Suite** for both frontend and backend
5. **Documentation** including API docs and user guides
6. **Deployment Scripts** for production environment
7. **Migration Guide** for existing users

## Technical Considerations

### Security:
- Implement proper authentication and authorization
- Sanitize all user inputs
- Use HTTPS in production
- Implement rate limiting
- Secure file access controls

### Performance:
- Optimize database queries
- Implement caching strategies
- Use CDN for static assets
- Optimize bundle sizes
- Implement lazy loading

### Scalability:
- Design for horizontal scaling
- Use connection pooling
- Implement proper logging and monitoring
- Design for multi-tenancy if needed

### Maintainability:
- Follow coding standards
- Implement comprehensive testing
- Use TypeScript for type safety
- Document all APIs and components
- Implement CI/CD pipeline

This migration will transform the V3 Crawler Platform into a modern, scalable, and user-friendly web application while preserving all existing functionality and adding new capabilities for better user experience and operational efficiency.
