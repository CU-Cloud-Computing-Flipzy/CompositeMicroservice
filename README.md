# CompositeMicroservice

# User & Address Service – API & Data Model Documentation

## 1. Data Models

### **User**
Stores core user identity information. Supports traditional username/password and Google auto-registration.

| Field       | Type     | Required | Description |
|-------------|----------|----------|-------------|
| `id`        | UUID     | Yes      | Unique identifier for the user (Primary Key) |
| `email`     | String   | Yes      | Email address (Unique), used for login identification |
| `username`  | String   | Yes      | Username (Unique) |
| `password`  | String   | No       | Nullable. `NULL` for Google login users |
| `google_id` | String   | No       | Google Account ID (`sub`), used for third-party binding |
| `full_name` | String   | No       | User full name |
| `avatar_url`| String   | No       | URL to avatar image |
| `phone`     | String   | No       | Phone number |
| `created_at`| DateTime | Yes      | Creation timestamp |
| `updated_at`| DateTime | Yes      | Last update timestamp |

---

### **Address**
Stores logistics / contact addresses. One-to-many relationship with **User**.

| Field        | Type     | Required | Description |
|--------------|----------|----------|-------------|
| `id`         | UUID     | Yes      | Unique identifier for the address (Primary Key) |
| `user_id`    | UUID     | Yes      | Associated User ID (Foreign Key) |
| `country`    | String   | Yes      | Country |
| `city`       | String   | Yes      | City |
| `street`     | String   | Yes      | Street / Detailed address |
| `postal_code`| String   | Yes      | Postal code |

---

## 2. API Endpoints

### **User Management (Users)**

| Method | Path | Description | Notes |
|--------|-------|-------------|--------|
| **GET** | `/users` | Get user list | Filtering by `email`, `username`; pagination (`limit`, `offset`) |
| **POST** | `/users` | Create user | With Google login logic: return existing user if email exists |
| **GET** | `/users/{user_id}` | Get user details | Supports **ETag** caching (`304 Not Modified`) |
| **PUT** | `/users/{user_id}` | Update user info | Supports **If-Match** header for concurrency control |
| **DELETE** | `/users/{user_id}` | Delete user | Cascades deletion of related addresses |
| **POST** | `/users/{user_id}/export` | Export user data | Async: triggers background job, returns **Job ID** |

---

### **Address Management (Addresses)**

| Method | Path | Description | Notes |
|--------|------|-------------|-------|
| **GET** | `/addresses` | Get address list | Filtering: `user_id`, `city`, `postal_code`; pagination |
| **POST** | `/addresses` | Create new address | Requires valid `user_id` |
| **GET** | `/addresses/{address_id}` | Get address details | Returns **HATEOAS Link headers** |
| **PUT** | `/addresses/{address_id}` | Update address fields | Update text information only |
| **DELETE** | `/addresses/{address_id}` | Delete address | Hard delete |

---

### **System & Jobs**

| Method | Path | Description |
|--------|------|-------------|
| **GET** | `/` | Root entry; returns welcome message and service status |
| **GET** | `/jobs/{job_id}` | Query background job status (e.g., export tasks) |

---

## End
This documentation covers database structure and RESTful API definitions for a user & address management service.


