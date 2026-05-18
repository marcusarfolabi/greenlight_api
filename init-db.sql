-- Create the greenlight role if it doesn't exist
CREATE ROLE greenlight WITH LOGIN PASSWORD 'greenlight' CREATEDB;

-- Grant permissions
ALTER ROLE greenlight CREATEDB;
