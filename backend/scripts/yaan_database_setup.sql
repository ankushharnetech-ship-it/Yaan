-- ============================================================================
-- YAAN database setup (PostgreSQL 15+)  -  structure + reference data, no business data
--
-- Creates the role, the database, every table / index / constraint, the btree_gist
-- extension and the lookup rows (vehicle types, trip types, expense categories ...).
--
-- Run it as a PostgreSQL superuser, with psql (it uses \connect):
--     psql -U postgres -f yaan_database_setup.sql
-- To stop it asking to overwrite, run it on a server where the "yaan" database does not exist yet.
--
-- BEFORE RUNNING: change the password on the CREATE ROLE line below, then put the same one in
-- backend/.env:  DATABASE_URL=postgresql+psycopg://yaan:<password>@localhost:5432/yaan
--
-- Afterwards create the first login (Super Admin):  cd backend; python -m app.seed
-- Schema version: Alembic head d4e8f1a7c2b6 (future migrations: alembic upgrade head)
-- ============================================================================

CREATE ROLE yaan LOGIN PASSWORD 'CHANGE_ME_BEFORE_RUNNING';
CREATE DATABASE yaan OWNER yaan ENCODING 'UTF8';
\connect yaan

BEGIN;

CREATE TABLE alembic_version (
    version_num VARCHAR(32) NOT NULL, 
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);

-- Running upgrade  -> 791f19ff2647

CREATE TABLE vendors (
    id SERIAL NOT NULL, 
    name VARCHAR(200) NOT NULL, 
    code VARCHAR(50) NOT NULL, 
    contact_name VARCHAR(200), 
    email VARCHAR(254), 
    mobile VARCHAR(20), 
    address TEXT, 
    status VARCHAR(30) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    UNIQUE (code), 
    CONSTRAINT activestatus CHECK (status IN ('active', 'inactive'))
);

CREATE TABLE application_settings (
    key VARCHAR(100) NOT NULL, 
    value VARCHAR(500) NOT NULL, 
    vendor_id INTEGER, 
    PRIMARY KEY (key), 
    FOREIGN KEY(vendor_id) REFERENCES vendors (id)
);

CREATE TABLE users (
    id SERIAL NOT NULL, 
    first_name VARCHAR(100) NOT NULL, 
    middle_name VARCHAR(100), 
    last_name VARCHAR(100) NOT NULL, 
    username VARCHAR(80) NOT NULL, 
    email VARCHAR(254) NOT NULL, 
    mobile VARCHAR(20), 
    gender VARCHAR(20), 
    address TEXT, 
    role VARCHAR(30) NOT NULL, 
    vendor_id INTEGER, 
    status VARCHAR(30) NOT NULL, 
    password_hash VARCHAR(255) NOT NULL, 
    temp_password_expires_at TIMESTAMP WITH TIME ZONE, 
    initial_setup_completed_at TIMESTAMP WITH TIME ZONE, 
    last_login_at TIMESTAMP WITH TIME ZONE, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT ck_users_vendor_scope CHECK ((role = 'super_admin' AND vendor_id IS NULL) OR (role <> 'super_admin' AND vendor_id IS NOT NULL)), 
    FOREIGN KEY(vendor_id) REFERENCES vendors (id), 
    UNIQUE (email), 
    UNIQUE (username), 
    CONSTRAINT role CHECK (role IN ('super_admin', 'vendor_admin', 'operator', 'driver')), 
    CONSTRAINT activestatus CHECK (status IN ('active', 'inactive'))
);

CREATE INDEX ix_users_vendor_id ON users (vendor_id);

CREATE TABLE audit_logs (
    id SERIAL NOT NULL, 
    actor_user_id INTEGER, 
    actor_role VARCHAR(30), 
    vendor_id INTEGER, 
    action VARCHAR(80) NOT NULL, 
    entity_type VARCHAR(60), 
    entity_id VARCHAR(60), 
    request_id VARCHAR(64), 
    detail JSON, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(actor_user_id) REFERENCES users (id), 
    FOREIGN KEY(vendor_id) REFERENCES vendors (id)
);

CREATE INDEX ix_audit_logs_action ON audit_logs (action);

CREATE INDEX ix_audit_logs_actor_user_id ON audit_logs (actor_user_id);

CREATE INDEX ix_audit_logs_created_at ON audit_logs (created_at);

CREATE INDEX ix_audit_logs_vendor_id ON audit_logs (vendor_id);

INSERT INTO alembic_version (version_num) VALUES ('791f19ff2647') RETURNING alembic_version.version_num;

-- Running upgrade 791f19ff2647 -> 894fdd3914dd

CREATE TABLE email_logs (
    id SERIAL NOT NULL, 
    user_id INTEGER, 
    vendor_id INTEGER, 
    to_email VARCHAR(254) NOT NULL, 
    template VARCHAR(60) NOT NULL, 
    status VARCHAR(20) NOT NULL, 
    provider_message_id VARCHAR(120), 
    failure_reason TEXT, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    sent_at TIMESTAMP WITH TIME ZONE, 
    PRIMARY KEY (id), 
    FOREIGN KEY(user_id) REFERENCES users (id), 
    FOREIGN KEY(vendor_id) REFERENCES vendors (id)
);

CREATE INDEX ix_email_logs_user_id ON email_logs (user_id);

CREATE INDEX ix_email_logs_vendor_id ON email_logs (vendor_id);

CREATE TABLE password_reset_tokens (
    id SERIAL NOT NULL, 
    user_id INTEGER NOT NULL, 
    token_hash VARCHAR(64) NOT NULL, 
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    used_at TIMESTAMP WITH TIME ZONE, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(user_id) REFERENCES users (id), 
    UNIQUE (token_hash)
);

CREATE INDEX ix_password_reset_tokens_user_id ON password_reset_tokens (user_id);

ALTER TABLE users ADD COLUMN token_version INTEGER DEFAULT '0' NOT NULL;

UPDATE alembic_version SET version_num='894fdd3914dd' WHERE alembic_version.version_num = '791f19ff2647';

-- Running upgrade 894fdd3914dd -> 1cb26f25c59d

CREATE TABLE lookup_values (
    id SERIAL NOT NULL, 
    category VARCHAR(40) NOT NULL, 
    code VARCHAR(40) NOT NULL, 
    label VARCHAR(100) NOT NULL, 
    sort_order INTEGER DEFAULT '0' NOT NULL, 
    is_active BOOLEAN DEFAULT 'true' NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT uq_lookup_category_code UNIQUE (category, code)
);

CREATE INDEX ix_lookup_values_category ON lookup_values (category);

CREATE TABLE customers (
    id SERIAL NOT NULL, 
    vendor_id INTEGER NOT NULL, 
    code VARCHAR(50) NOT NULL, 
    name VARCHAR(200) NOT NULL, 
    contact_person VARCHAR(200), 
    email VARCHAR(254), 
    phone VARCHAR(20), 
    address TEXT, 
    status VARCHAR(30) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(vendor_id) REFERENCES vendors (id), 
    CONSTRAINT uq_customer_vendor_code UNIQUE (vendor_id, code), 
    CONSTRAINT activestatus CHECK (status IN ('active', 'inactive'))
);

CREATE INDEX ix_customers_vendor_id ON customers (vendor_id);

CREATE TABLE vehicles (
    id SERIAL NOT NULL, 
    code VARCHAR(20), 
    vendor_id INTEGER NOT NULL, 
    vehicle_number VARCHAR(20) NOT NULL, 
    vehicle_code VARCHAR(50) NOT NULL, 
    vehicle_type_id INTEGER NOT NULL, 
    model VARCHAR(100) NOT NULL, 
    capacity INTEGER NOT NULL, 
    status VARCHAR(30) NOT NULL, 
    make VARCHAR(100), 
    chassis_number VARCHAR(60), 
    fuel_type_id INTEGER, 
    induction_type_id INTEGER, 
    induction_date DATE, 
    gps_imei VARCHAR(30), 
    billing_profile VARCHAR(100), 
    date_of_joining DATE, 
    shed_location TEXT, 
    locality VARCHAR(100), 
    latitude FLOAT, 
    longitude FLOAT, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT ck_vehicle_capacity_positive CHECK (capacity > 0), 
    FOREIGN KEY(fuel_type_id) REFERENCES lookup_values (id), 
    FOREIGN KEY(induction_type_id) REFERENCES lookup_values (id), 
    FOREIGN KEY(vehicle_type_id) REFERENCES lookup_values (id), 
    FOREIGN KEY(vendor_id) REFERENCES vendors (id), 
    UNIQUE (code), 
    UNIQUE (vehicle_number), 
    CONSTRAINT uq_vehicle_vendor_code UNIQUE (vendor_id, vehicle_code), 
    CONSTRAINT activestatus CHECK (status IN ('active', 'inactive'))
);

CREATE INDEX ix_vehicles_vendor_id ON vehicles (vendor_id);

CREATE TABLE drivers (
    id SERIAL NOT NULL, 
    code VARCHAR(20), 
    vendor_id INTEGER NOT NULL, 
    first_name VARCHAR(100) NOT NULL, 
    middle_name VARCHAR(100), 
    last_name VARCHAR(100) NOT NULL, 
    contact_number VARCHAR(20) NOT NULL, 
    gender VARCHAR(10) NOT NULL, 
    date_of_birth DATE, 
    date_of_joining DATE, 
    experience_months INTEGER, 
    license_type_id INTEGER NOT NULL, 
    license_number VARCHAR(50) NOT NULL, 
    emergency_contact VARCHAR(20), 
    rest_days JSON, 
    languages JSON, 
    status VARCHAR(30) NOT NULL, 
    status_comment TEXT, 
    home_address TEXT, 
    locality VARCHAR(100), 
    latitude FLOAT, 
    longitude FLOAT, 
    induction_date DATE, 
    induction_type_id INTEGER, 
    default_vehicle_id INTEGER, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(default_vehicle_id) REFERENCES vehicles (id), 
    FOREIGN KEY(induction_type_id) REFERENCES lookup_values (id), 
    FOREIGN KEY(license_type_id) REFERENCES lookup_values (id), 
    FOREIGN KEY(vendor_id) REFERENCES vendors (id), 
    UNIQUE (code), 
    CONSTRAINT uq_driver_vendor_license UNIQUE (vendor_id, license_number), 
    CONSTRAINT activestatus CHECK (status IN ('active', 'inactive'))
);

CREATE INDEX ix_drivers_vendor_id ON drivers (vendor_id);

CREATE TABLE sites (
    id SERIAL NOT NULL, 
    vendor_id INTEGER NOT NULL, 
    customer_id INTEGER NOT NULL, 
    name VARCHAR(200) NOT NULL, 
    address TEXT NOT NULL, 
    city VARCHAR(100), 
    latitude FLOAT, 
    longitude FLOAT, 
    status VARCHAR(30) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(customer_id) REFERENCES customers (id), 
    FOREIGN KEY(vendor_id) REFERENCES vendors (id), 
    CONSTRAINT uq_site_customer_name UNIQUE (customer_id, name), 
    CONSTRAINT activestatus CHECK (status IN ('active', 'inactive'))
);

CREATE INDEX ix_sites_customer_id ON sites (customer_id);

CREATE INDEX ix_sites_vendor_id ON sites (vendor_id);

CREATE TABLE employees (
    id SERIAL NOT NULL, 
    vendor_id INTEGER NOT NULL, 
    customer_id INTEGER NOT NULL, 
    site_id INTEGER, 
    employee_code VARCHAR(50) NOT NULL, 
    first_name VARCHAR(100) NOT NULL, 
    last_name VARCHAR(100) NOT NULL, 
    mobile VARCHAR(20) NOT NULL, 
    email VARCHAR(254), 
    gender VARCHAR(10) NOT NULL, 
    department VARCHAR(100), 
    pickup_address TEXT, 
    pickup_latitude FLOAT, 
    pickup_longitude FLOAT, 
    drop_address TEXT, 
    drop_latitude FLOAT, 
    drop_longitude FLOAT, 
    status VARCHAR(30) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(customer_id) REFERENCES customers (id), 
    FOREIGN KEY(site_id) REFERENCES sites (id), 
    FOREIGN KEY(vendor_id) REFERENCES vendors (id), 
    CONSTRAINT uq_employee_customer_code UNIQUE (customer_id, employee_code), 
    CONSTRAINT activestatus CHECK (status IN ('active', 'inactive'))
);

CREATE INDEX ix_employees_customer_id ON employees (customer_id);

CREATE INDEX ix_employees_site_id ON employees (site_id);

CREATE INDEX ix_employees_vendor_id ON employees (vendor_id);

ALTER TABLE users ADD COLUMN driver_id INTEGER;

ALTER TABLE users ADD UNIQUE (driver_id);

ALTER TABLE users ADD FOREIGN KEY(driver_id) REFERENCES drivers (id);

INSERT INTO lookup_values (category, code, label, sort_order, is_active) VALUES ('vehicle_type', 'hatchback', 'Hatchback', 0, true);

INSERT INTO lookup_values (category, code, label, sort_order, is_active) VALUES ('vehicle_type', 'sedan', 'Sedan', 1, true);

INSERT INTO lookup_values (category, code, label, sort_order, is_active) VALUES ('vehicle_type', 'suv', 'SUV', 2, true);

INSERT INTO lookup_values (category, code, label, sort_order, is_active) VALUES ('vehicle_type', 'muv', 'MUV', 3, true);

INSERT INTO lookup_values (category, code, label, sort_order, is_active) VALUES ('vehicle_type', 'tempo_traveller', 'Tempo Traveller', 4, true);

INSERT INTO lookup_values (category, code, label, sort_order, is_active) VALUES ('vehicle_type', 'mini_bus', 'Mini Bus', 5, true);

INSERT INTO lookup_values (category, code, label, sort_order, is_active) VALUES ('vehicle_type', 'bus', 'Bus', 6, true);

INSERT INTO lookup_values (category, code, label, sort_order, is_active) VALUES ('fuel_type', 'petrol', 'Petrol', 0, true);

INSERT INTO lookup_values (category, code, label, sort_order, is_active) VALUES ('fuel_type', 'diesel', 'Diesel', 1, true);

INSERT INTO lookup_values (category, code, label, sort_order, is_active) VALUES ('fuel_type', 'cng', 'CNG', 2, true);

INSERT INTO lookup_values (category, code, label, sort_order, is_active) VALUES ('fuel_type', 'electric', 'Electric', 3, true);

INSERT INTO lookup_values (category, code, label, sort_order, is_active) VALUES ('fuel_type', 'hybrid', 'Hybrid', 4, true);

INSERT INTO lookup_values (category, code, label, sort_order, is_active) VALUES ('license_type', 'lmv', 'LMV', 0, true);

INSERT INTO lookup_values (category, code, label, sort_order, is_active) VALUES ('license_type', 'lmv_transport', 'LMV - Transport', 1, true);

INSERT INTO lookup_values (category, code, label, sort_order, is_active) VALUES ('license_type', 'hmv', 'HMV', 2, true);

INSERT INTO lookup_values (category, code, label, sort_order, is_active) VALUES ('license_type', 'hpmv', 'HPMV', 3, true);

INSERT INTO lookup_values (category, code, label, sort_order, is_active) VALUES ('induction_type', 'new', 'New', 0, true);

INSERT INTO lookup_values (category, code, label, sort_order, is_active) VALUES ('induction_type', 're-induction', 'Re-induction', 1, true);

INSERT INTO lookup_values (category, code, label, sort_order, is_active) VALUES ('induction_type', 'transfer', 'Transfer', 2, true);

INSERT INTO lookup_values (category, code, label, sort_order, is_active) VALUES ('trip_type', 'pickup', 'Pickup', 0, true);

INSERT INTO lookup_values (category, code, label, sort_order, is_active) VALUES ('trip_type', 'drop', 'Drop', 1, true);

UPDATE alembic_version SET version_num='1cb26f25c59d' WHERE alembic_version.version_num = '894fdd3914dd';

-- Running upgrade 1cb26f25c59d -> 76cfed094abb

CREATE EXTENSION IF NOT EXISTS btree_gist;

CREATE TABLE shift_definitions (
    id SERIAL NOT NULL, 
    vendor_id INTEGER NOT NULL, 
    customer_id INTEGER NOT NULL, 
    name VARCHAR(100) NOT NULL, 
    start_time TIME WITHOUT TIME ZONE NOT NULL, 
    end_time TIME WITHOUT TIME ZONE NOT NULL, 
    status VARCHAR(30) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(customer_id) REFERENCES customers (id), 
    FOREIGN KEY(vendor_id) REFERENCES vendors (id), 
    CONSTRAINT uq_shift_customer_name UNIQUE (customer_id, name), 
    CONSTRAINT activestatus CHECK (status IN ('active', 'inactive'))
);

CREATE INDEX ix_shift_definitions_customer_id ON shift_definitions (customer_id);

CREATE INDEX ix_shift_definitions_vendor_id ON shift_definitions (vendor_id);

CREATE TABLE trips (
    id SERIAL NOT NULL, 
    code VARCHAR(20), 
    vendor_id INTEGER NOT NULL, 
    customer_id INTEGER NOT NULL, 
    site_id INTEGER NOT NULL, 
    trip_type_id INTEGER NOT NULL, 
    shift_id INTEGER, 
    scheduled_start TIMESTAMP WITH TIME ZONE NOT NULL, 
    scheduled_end TIMESTAMP WITH TIME ZONE NOT NULL, 
    block_end TIMESTAMP WITH TIME ZONE NOT NULL, 
    route_name VARCHAR(200), 
    special_instructions TEXT, 
    pickup_address TEXT NOT NULL, 
    pickup_latitude FLOAT, 
    pickup_longitude FLOAT, 
    drop_address TEXT NOT NULL, 
    drop_latitude FLOAT, 
    drop_longitude FLOAT, 
    passenger_count INTEGER NOT NULL, 
    escort_required BOOLEAN NOT NULL, 
    required_capacity INTEGER NOT NULL, 
    driver_id INTEGER NOT NULL, 
    vehicle_id INTEGER NOT NULL, 
    status VARCHAR(30) NOT NULL, 
    created_by INTEGER NOT NULL, 
    accepted_at TIMESTAMP WITH TIME ZONE, 
    started_at TIMESTAMP WITH TIME ZONE, 
    completed_at TIMESTAMP WITH TIME ZONE, 
    cancelled_at TIMESTAMP WITH TIME ZONE, 
    cancelled_by INTEGER, 
    cancellation_reason TEXT, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT ex_trip_driver_overlap EXCLUDE USING gist (driver_id WITH =, tstzrange(scheduled_start, block_end) WITH &&) WHERE (status <> 'cancelled'), 
    CONSTRAINT ex_trip_vehicle_overlap EXCLUDE USING gist (vehicle_id WITH =, tstzrange(scheduled_start, block_end) WITH &&) WHERE (status <> 'cancelled'), 
    CONSTRAINT ck_trip_block_end CHECK (block_end >= scheduled_end), 
    CONSTRAINT ck_trip_end_after_start CHECK (scheduled_end > scheduled_start), 
    FOREIGN KEY(cancelled_by) REFERENCES users (id), 
    FOREIGN KEY(created_by) REFERENCES users (id), 
    FOREIGN KEY(customer_id) REFERENCES customers (id), 
    FOREIGN KEY(driver_id) REFERENCES drivers (id), 
    FOREIGN KEY(shift_id) REFERENCES shift_definitions (id), 
    FOREIGN KEY(site_id) REFERENCES sites (id), 
    FOREIGN KEY(trip_type_id) REFERENCES lookup_values (id), 
    FOREIGN KEY(vehicle_id) REFERENCES vehicles (id), 
    FOREIGN KEY(vendor_id) REFERENCES vendors (id), 
    UNIQUE (code), 
    CONSTRAINT tripstatus CHECK (status IN ('scheduled', 'assigned', 'accepted', 'started', 'completed', 'cancelled'))
);

CREATE INDEX ix_trips_customer_id ON trips (customer_id);

CREATE INDEX ix_trips_driver_id ON trips (driver_id);

CREATE INDEX ix_trips_status ON trips (status);

CREATE INDEX ix_trips_vehicle_id ON trips (vehicle_id);

CREATE INDEX ix_trips_vendor_id ON trips (vendor_id);

CREATE INDEX ix_trips_vendor_start ON trips (vendor_id, scheduled_start);

CREATE TABLE trip_assignments (
    id SERIAL NOT NULL, 
    trip_id INTEGER NOT NULL, 
    driver_id INTEGER NOT NULL, 
    vehicle_id INTEGER NOT NULL, 
    assigned_by INTEGER NOT NULL, 
    assigned_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    released_at TIMESTAMP WITH TIME ZONE, 
    PRIMARY KEY (id), 
    FOREIGN KEY(assigned_by) REFERENCES users (id), 
    FOREIGN KEY(driver_id) REFERENCES drivers (id), 
    FOREIGN KEY(trip_id) REFERENCES trips (id), 
    FOREIGN KEY(vehicle_id) REFERENCES vehicles (id)
);

CREATE INDEX ix_trip_assignments_trip_id ON trip_assignments (trip_id);

CREATE TABLE trip_passengers (
    id SERIAL NOT NULL, 
    trip_id INTEGER NOT NULL, 
    employee_id INTEGER NOT NULL, 
    sequence INTEGER NOT NULL, 
    pickup_address TEXT, 
    drop_address TEXT, 
    name VARCHAR(200) NOT NULL, 
    mobile VARCHAR(20) NOT NULL, 
    gender VARCHAR(10) NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(employee_id) REFERENCES employees (id), 
    FOREIGN KEY(trip_id) REFERENCES trips (id), 
    CONSTRAINT uq_trip_passenger UNIQUE (trip_id, employee_id)
);

CREATE INDEX ix_trip_passengers_employee_id ON trip_passengers (employee_id);

CREATE INDEX ix_trip_passengers_trip_id ON trip_passengers (trip_id);

CREATE TABLE trip_status_history (
    id SERIAL NOT NULL, 
    trip_id INTEGER NOT NULL, 
    from_status VARCHAR(20), 
    to_status VARCHAR(20) NOT NULL, 
    changed_by INTEGER NOT NULL, 
    changed_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    note TEXT, 
    PRIMARY KEY (id), 
    FOREIGN KEY(changed_by) REFERENCES users (id), 
    FOREIGN KEY(trip_id) REFERENCES trips (id)
);

CREATE INDEX ix_trip_status_history_trip_id ON trip_status_history (trip_id);

ALTER TABLE employees ADD COLUMN shift_id INTEGER;

ALTER TABLE employees ADD FOREIGN KEY(shift_id) REFERENCES shift_definitions (id);

UPDATE alembic_version SET version_num='76cfed094abb' WHERE alembic_version.version_num = '1cb26f25c59d';

-- Running upgrade 76cfed094abb -> f2d65299995f

CREATE TABLE sms_logs (
    id SERIAL NOT NULL, 
    vendor_id INTEGER NOT NULL, 
    trip_id INTEGER, 
    recipient_type VARCHAR(20) NOT NULL, 
    driver_id INTEGER, 
    employee_id INTEGER, 
    recipient_name VARCHAR(200), 
    phone VARCHAR(32) NOT NULL, 
    template VARCHAR(60) NOT NULL, 
    body TEXT NOT NULL, 
    status VARCHAR(20) NOT NULL, 
    provider_message_id VARCHAR(64), 
    failure_reason TEXT, 
    attempts INTEGER DEFAULT '0' NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    sent_at TIMESTAMP WITH TIME ZONE, 
    delivered_at TIMESTAMP WITH TIME ZONE, 
    PRIMARY KEY (id), 
    FOREIGN KEY(driver_id) REFERENCES drivers (id), 
    FOREIGN KEY(employee_id) REFERENCES employees (id), 
    FOREIGN KEY(trip_id) REFERENCES trips (id), 
    FOREIGN KEY(vendor_id) REFERENCES vendors (id)
);

CREATE INDEX ix_sms_logs_driver_id ON sms_logs (driver_id);

CREATE INDEX ix_sms_logs_provider_message_id ON sms_logs (provider_message_id);

CREATE INDEX ix_sms_logs_status ON sms_logs (status);

CREATE INDEX ix_sms_logs_trip_id ON sms_logs (trip_id);

CREATE INDEX ix_sms_logs_vendor_id ON sms_logs (vendor_id);

DROP TABLE application_settings;

CREATE TABLE application_settings (
    id SERIAL NOT NULL, 
    key VARCHAR(100) NOT NULL, 
    value VARCHAR(500) NOT NULL, 
    vendor_id INTEGER, 
    PRIMARY KEY (id), 
    FOREIGN KEY(vendor_id) REFERENCES vendors (id)
);

CREATE UNIQUE INDEX uq_setting_key_vendor ON application_settings (key, coalesce(vendor_id, 0));

UPDATE alembic_version SET version_num='f2d65299995f' WHERE alembic_version.version_num = '76cfed094abb';

-- Running upgrade f2d65299995f -> 5d9b1ca9be86

CREATE TABLE compliance_items (
    id SERIAL NOT NULL, 
    vendor_id INTEGER NOT NULL, 
    subject_type VARCHAR(10) NOT NULL, 
    driver_id INTEGER, 
    vehicle_id INTEGER, 
    doc_type_id INTEGER NOT NULL, 
    title VARCHAR(120), 
    reference_number VARCHAR(100), 
    issue_date DATE, 
    expiry_date DATE NOT NULL, 
    notes TEXT, 
    status VARCHAR(30) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT ck_compliance_one_subject CHECK ((subject_type = 'driver' AND driver_id IS NOT NULL AND vehicle_id IS NULL) OR (subject_type = 'vehicle' AND vehicle_id IS NOT NULL AND driver_id IS NULL)), 
    CONSTRAINT ck_compliance_dates CHECK (issue_date IS NULL OR expiry_date >= issue_date), 
    FOREIGN KEY(doc_type_id) REFERENCES lookup_values (id), 
    FOREIGN KEY(driver_id) REFERENCES drivers (id), 
    FOREIGN KEY(vehicle_id) REFERENCES vehicles (id), 
    FOREIGN KEY(vendor_id) REFERENCES vendors (id), 
    CONSTRAINT activestatus CHECK (status IN ('active', 'inactive'))
);

CREATE INDEX ix_compliance_items_driver_id ON compliance_items (driver_id);

CREATE INDEX ix_compliance_items_expiry_date ON compliance_items (expiry_date);

CREATE INDEX ix_compliance_items_vehicle_id ON compliance_items (vehicle_id);

CREATE INDEX ix_compliance_items_vendor_id ON compliance_items (vendor_id);

INSERT INTO lookup_values (category, code, label, sort_order, is_active) VALUES ('driver_doc_type', 'driving_licence', 'Driving licence', 0, true);

INSERT INTO lookup_values (category, code, label, sort_order, is_active) VALUES ('driver_doc_type', 'medical_certificate', 'Medical certificate', 1, true);

INSERT INTO lookup_values (category, code, label, sort_order, is_active) VALUES ('driver_doc_type', 'police_verification', 'Police verification', 2, true);

INSERT INTO lookup_values (category, code, label, sort_order, is_active) VALUES ('driver_doc_type', 'badge_permit', 'Badge / permit', 3, true);

INSERT INTO lookup_values (category, code, label, sort_order, is_active) VALUES ('driver_doc_type', 'id_proof', 'ID proof', 4, true);

INSERT INTO lookup_values (category, code, label, sort_order, is_active) VALUES ('driver_doc_type', 'address_proof', 'Address proof', 5, true);

INSERT INTO lookup_values (category, code, label, sort_order, is_active) VALUES ('driver_doc_type', 'other', 'Other', 6, true);

INSERT INTO lookup_values (category, code, label, sort_order, is_active) VALUES ('vehicle_doc_type', 'registration_certificate', 'Registration certificate', 0, true);

INSERT INTO lookup_values (category, code, label, sort_order, is_active) VALUES ('vehicle_doc_type', 'permit', 'Permit', 1, true);

INSERT INTO lookup_values (category, code, label, sort_order, is_active) VALUES ('vehicle_doc_type', 'insurance', 'Insurance', 2, true);

INSERT INTO lookup_values (category, code, label, sort_order, is_active) VALUES ('vehicle_doc_type', 'road_tax', 'Road tax', 3, true);

INSERT INTO lookup_values (category, code, label, sort_order, is_active) VALUES ('vehicle_doc_type', 'fitness_certificate', 'Fitness certificate', 4, true);

INSERT INTO lookup_values (category, code, label, sort_order, is_active) VALUES ('vehicle_doc_type', 'pollution_puc', 'Pollution (PUC)', 5, true);

INSERT INTO lookup_values (category, code, label, sort_order, is_active) VALUES ('vehicle_doc_type', 'other', 'Other', 6, true);

UPDATE alembic_version SET version_num='5d9b1ca9be86' WHERE alembic_version.version_num = 'f2d65299995f';

-- Running upgrade 5d9b1ca9be86 -> 46d50334ae2c

ALTER TABLE employees RENAME pickup_address TO address;

ALTER TABLE employees RENAME pickup_latitude TO latitude;

ALTER TABLE employees RENAME pickup_longitude TO longitude;

UPDATE employees SET address = drop_address WHERE address IS NULL;

ALTER TABLE employees DROP COLUMN drop_address;

ALTER TABLE employees DROP COLUMN drop_latitude;

ALTER TABLE employees DROP COLUMN drop_longitude;

ALTER TABLE trip_passengers RENAME pickup_address TO address;

UPDATE trip_passengers SET address = drop_address WHERE address IS NULL;

ALTER TABLE trip_passengers DROP COLUMN drop_address;

UPDATE alembic_version SET version_num='46d50334ae2c' WHERE alembic_version.version_num = '5d9b1ca9be86';

-- Running upgrade 46d50334ae2c -> 47c093b827c9

CREATE TABLE expenses (
    id SERIAL NOT NULL, 
    code VARCHAR(20), 
    vendor_id INTEGER NOT NULL, 
    expense_date DATE NOT NULL, 
    category_id INTEGER NOT NULL, 
    amount NUMERIC(12, 2) NOT NULL, 
    payment_method VARCHAR(20) NOT NULL, 
    description TEXT, 
    vehicle_id INTEGER, 
    driver_id INTEGER, 
    created_by INTEGER NOT NULL, 
    status VARCHAR(10) NOT NULL, 
    void_reason TEXT, 
    voided_by INTEGER, 
    voided_at TIMESTAMP WITH TIME ZONE, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT ck_expense_status CHECK (status IN ('recorded', 'voided')), 
    CONSTRAINT ck_expense_amount_positive CHECK (amount > 0), 
    FOREIGN KEY(category_id) REFERENCES lookup_values (id), 
    FOREIGN KEY(created_by) REFERENCES users (id), 
    FOREIGN KEY(driver_id) REFERENCES drivers (id), 
    FOREIGN KEY(vehicle_id) REFERENCES vehicles (id), 
    FOREIGN KEY(vendor_id) REFERENCES vendors (id), 
    FOREIGN KEY(voided_by) REFERENCES users (id), 
    UNIQUE (code)
);

CREATE INDEX ix_expenses_created_by ON expenses (created_by);

CREATE INDEX ix_expenses_driver_id ON expenses (driver_id);

CREATE INDEX ix_expenses_vehicle_id ON expenses (vehicle_id);

CREATE INDEX ix_expenses_vendor_date ON expenses (vendor_id, expense_date);

CREATE INDEX ix_expenses_vendor_id ON expenses (vendor_id);

INSERT INTO lookup_values (category, code, label, sort_order, is_active) VALUES ('expense_category', 'fuel', 'Fuel', 0, true);

INSERT INTO lookup_values (category, code, label, sort_order, is_active) VALUES ('expense_category', 'maintenance_repair', 'Maintenance & repair', 1, true);

INSERT INTO lookup_values (category, code, label, sort_order, is_active) VALUES ('expense_category', 'tyres', 'Tyres', 2, true);

INSERT INTO lookup_values (category, code, label, sort_order, is_active) VALUES ('expense_category', 'insurance', 'Insurance', 3, true);

INSERT INTO lookup_values (category, code, label, sort_order, is_active) VALUES ('expense_category', 'toll_parking', 'Toll & parking', 4, true);

INSERT INTO lookup_values (category, code, label, sort_order, is_active) VALUES ('expense_category', 'cleaning', 'Cleaning', 5, true);

INSERT INTO lookup_values (category, code, label, sort_order, is_active) VALUES ('expense_category', 'fines_challans', 'Fines & challans', 6, true);

INSERT INTO lookup_values (category, code, label, sort_order, is_active) VALUES ('expense_category', 'driver_allowance', 'Driver allowance', 7, true);

INSERT INTO lookup_values (category, code, label, sort_order, is_active) VALUES ('expense_category', 'spare_parts', 'Spare parts', 8, true);

INSERT INTO lookup_values (category, code, label, sort_order, is_active) VALUES ('expense_category', 'other', 'Other', 9, true);

UPDATE alembic_version SET version_num='47c093b827c9' WHERE alembic_version.version_num = '46d50334ae2c';

-- Running upgrade 47c093b827c9 -> 118ad3d25ae1

ALTER TABLE trips ALTER COLUMN driver_id DROP NOT NULL;

ALTER TABLE trips ALTER COLUMN vehicle_id DROP NOT NULL;

UPDATE alembic_version SET version_num='118ad3d25ae1' WHERE alembic_version.version_num = '47c093b827c9';

-- Running upgrade 118ad3d25ae1 -> 3f90f0157dea

ALTER TABLE customers ADD COLUMN latitude FLOAT;

ALTER TABLE customers ADD COLUMN longitude FLOAT;

UPDATE alembic_version SET version_num='3f90f0157dea' WHERE alembic_version.version_num = '118ad3d25ae1';

-- Running upgrade 3f90f0157dea -> b94e5aedaad5

ALTER TABLE drivers ADD COLUMN email VARCHAR(254);

ALTER TABLE email_logs ADD COLUMN trip_id INTEGER;

ALTER TABLE email_logs ADD COLUMN recipient_type VARCHAR(20);

ALTER TABLE email_logs ADD COLUMN employee_id INTEGER;

ALTER TABLE email_logs ADD COLUMN driver_id INTEGER;

ALTER TABLE email_logs ADD COLUMN recipient_name VARCHAR(200);

ALTER TABLE email_logs ADD COLUMN subject VARCHAR(200);

ALTER TABLE email_logs ADD COLUMN body TEXT;

ALTER TABLE email_logs ADD COLUMN attempts INTEGER DEFAULT '0' NOT NULL;

CREATE INDEX ix_email_logs_driver_id ON email_logs (driver_id);

CREATE INDEX ix_email_logs_trip_id ON email_logs (trip_id);

ALTER TABLE email_logs ADD FOREIGN KEY(employee_id) REFERENCES employees (id);

ALTER TABLE email_logs ADD FOREIGN KEY(trip_id) REFERENCES trips (id);

ALTER TABLE email_logs ADD FOREIGN KEY(driver_id) REFERENCES drivers (id);

ALTER TABLE trip_passengers ADD COLUMN otp_seed VARCHAR(32);

ALTER TABLE trip_passengers ADD COLUMN otp_attempts INTEGER DEFAULT '0' NOT NULL;

ALTER TABLE trip_passengers ADD COLUMN otp_verified_at TIMESTAMP WITH TIME ZONE;

ALTER TABLE trip_passengers ADD COLUMN otp_verified_by INTEGER;

ALTER TABLE trip_passengers ADD COLUMN not_dropped_at TIMESTAMP WITH TIME ZONE;

ALTER TABLE trip_passengers ADD COLUMN not_dropped_reason TEXT;

ALTER TABLE trip_passengers ADD COLUMN not_dropped_by INTEGER;

ALTER TABLE trip_passengers ADD FOREIGN KEY(not_dropped_by) REFERENCES users (id);

ALTER TABLE trip_passengers ADD FOREIGN KEY(otp_verified_by) REFERENCES users (id);

UPDATE trip_passengers SET otp_seed = md5(random()::text || id::text) WHERE trip_id IN (SELECT id FROM trips WHERE status IN ('assigned', 'accepted', 'started'));

UPDATE alembic_version SET version_num='b94e5aedaad5' WHERE alembic_version.version_num = '3f90f0157dea';

-- Running upgrade b94e5aedaad5 -> c7a1d4e2b9f3

ALTER TABLE users ADD COLUMN customer_id INTEGER;

CREATE INDEX ix_users_customer_id ON users (customer_id);

ALTER TABLE users ADD CONSTRAINT fk_users_customer_id FOREIGN KEY(customer_id) REFERENCES customers (id);

UPDATE alembic_version SET version_num='c7a1d4e2b9f3' WHERE alembic_version.version_num = 'b94e5aedaad5';

-- Running upgrade c7a1d4e2b9f3 -> d4e8f1a7c2b6

ALTER TABLE trips ADD COLUMN last_latitude FLOAT;

ALTER TABLE trips ADD COLUMN last_longitude FLOAT;

ALTER TABLE trips ADD COLUMN last_location_at TIMESTAMP WITH TIME ZONE;

UPDATE alembic_version SET version_num='d4e8f1a7c2b6' WHERE alembic_version.version_num = 'c7a1d4e2b9f3';

COMMIT;


-- Hand everything created above to the application role
DO $$
DECLARE r record;
BEGIN
    FOR r IN SELECT tablename FROM pg_tables WHERE schemaname = 'public' LOOP
        EXECUTE format('ALTER TABLE public.%I OWNER TO yaan', r.tablename);
    END LOOP;
    FOR r IN SELECT sequencename FROM pg_sequences WHERE schemaname = 'public' LOOP
        EXECUTE format('ALTER SEQUENCE public.%I OWNER TO yaan', r.sequencename);
    END LOOP;
END $$;
