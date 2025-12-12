CREATE SCHEMA "public";
CREATE TABLE "event_parse_log" (
	"id" serial PRIMARY KEY,
	"event_id" integer,
	"raw_text_gz" bytea,
	"parsed_json" jsonb,
	"status" text,
	"error" text,
	"created_at" timestamp DEFAULT now()
);
CREATE TABLE "event_participation" (
	"id" serial PRIMARY KEY,
	"event_id" integer,
	"team_name" text,
	"tournament_team_id" integer,
	"score" integer,
	"position" integer,
	"num_players" integer,
	"is_visiting" boolean DEFAULT false,
	"is_tournament" boolean DEFAULT false,
	"updated_at" timestamp
);
CREATE TABLE "event_photos" (
	"id" serial PRIMARY KEY,
	"event_id" integer,
	"photo_url" text
);
CREATE TABLE "events" (
	"id" serial PRIMARY KEY,
	"host_id" integer,
	"venue_id" integer UNIQUE,
	"event_date" date NOT NULL UNIQUE,
	"highlights" text,
	"pdf_url" text,
	"ai_recap" text,
	"status" text DEFAULT 'unposted',
	"fb_event_url" text,
	"created_at" timestamp DEFAULT now(),
	"show_type" text DEFAULT 'gsp',
	"updated_at" timestamp,
	"is_validated" boolean DEFAULT false,
	"total_players" integer,
	"total_teams" integer,
	CONSTRAINT "uniq_venue_date" UNIQUE("venue_id","event_date")
);
CREATE TABLE "hosts" (
	"id" serial PRIMARY KEY,
	"name" text NOT NULL CONSTRAINT "hosts_name_key" UNIQUE,
	"phone" text,
	"email" text
);
CREATE TABLE "tournament_team_scores" (
	"id" serial PRIMARY KEY,
	"tournament_team_id" integer NOT NULL UNIQUE,
	"venue_id" integer NOT NULL UNIQUE,
	"week_id" integer NOT NULL UNIQUE,
	"event_id" integer,
	"points" integer DEFAULT 0,
	"num_players" integer,
	"is_validated" boolean DEFAULT false,
	"updated_at" timestamp with time zone DEFAULT now(),
	CONSTRAINT "tournament_team_scores_tournament_team_id_venue_id_week_id_key" UNIQUE("tournament_team_id","venue_id","week_id")
);
CREATE TABLE "tournament_teams" (
	"id" serial PRIMARY KEY,
	"name" text NOT NULL CONSTRAINT "tournament_teams_name_key" UNIQUE,
	"home_venue_id" integer,
	"captain_name" text,
	"captain_email" text,
	"captain_phone" text,
	"player_count" integer,
	"created_at" timestamp DEFAULT now(),
	"access_key" text CONSTRAINT "tournament_teams_access_key_key" UNIQUE
);
CREATE TABLE "tournament_weeks" (
	"id" serial PRIMARY KEY,
	"week_ending" date NOT NULL CONSTRAINT "tournament_weeks_week_ending_key" UNIQUE,
	"created_at" timestamp DEFAULT now()
);
CREATE TABLE "venues" (
	"id" serial PRIMARY KEY,
	"name" text NOT NULL CONSTRAINT "venues_name_key" UNIQUE,
	"default_day" text,
	"default_time" text,
	"default_host_id" integer,
	"show_type" text DEFAULT 'gsp',
	"access_key" text CONSTRAINT "venues_access_key_key" UNIQUE,
	"is_active" boolean DEFAULT true,
	"notes" text
);
ALTER TABLE "event_parse_log" ADD CONSTRAINT "event_parse_log_event_id_fkey" FOREIGN KEY ("event_id") REFERENCES "events"("id") ON DELETE CASCADE;
ALTER TABLE "event_participation" ADD CONSTRAINT "event_participation_event_id_fkey" FOREIGN KEY ("event_id") REFERENCES "events"("id") ON DELETE CASCADE;
ALTER TABLE "event_photos" ADD CONSTRAINT "event_photos_event_id_fkey" FOREIGN KEY ("event_id") REFERENCES "events"("id") ON DELETE CASCADE;
ALTER TABLE "events" ADD CONSTRAINT "events_host_id_fkey" FOREIGN KEY ("host_id") REFERENCES "hosts"("id");
ALTER TABLE "tournament_team_scores" ADD CONSTRAINT "tournament_team_scores_event_id_fkey" FOREIGN KEY ("event_id") REFERENCES "events"("id") ON DELETE SET NULL;
ALTER TABLE "tournament_team_scores" ADD CONSTRAINT "tournament_team_scores_tournament_team_id_fkey" FOREIGN KEY ("tournament_team_id") REFERENCES "tournament_teams"("id") ON DELETE CASCADE;
ALTER TABLE "tournament_team_scores" ADD CONSTRAINT "tournament_team_scores_venue_id_fkey" FOREIGN KEY ("venue_id") REFERENCES "venues"("id") ON DELETE CASCADE;
ALTER TABLE "tournament_team_scores" ADD CONSTRAINT "tournament_team_scores_week_id_fkey" FOREIGN KEY ("week_id") REFERENCES "tournament_weeks"("id") ON DELETE CASCADE;
CREATE UNIQUE INDEX "event_parse_log_pkey" ON "event_parse_log" ("id");
CREATE UNIQUE INDEX "event_participation_pkey" ON "event_participation" ("id");
CREATE INDEX "idx_event_participation_event_pos" ON "event_participation" ("event_id","position");
CREATE UNIQUE INDEX "event_photos_pkey" ON "event_photos" ("id");
CREATE INDEX "idx_event_photos_event" ON "event_photos" ("event_id");
CREATE UNIQUE INDEX "events_pkey" ON "events" ("id");
CREATE UNIQUE INDEX "uniq_venue_date" ON "events" ("venue_id","event_date");
CREATE UNIQUE INDEX "hosts_name_key" ON "hosts" ("name");
CREATE UNIQUE INDEX "hosts_pkey" ON "hosts" ("id");
CREATE INDEX "idx_tts_team_week" ON "tournament_team_scores" ("tournament_team_id","week_id");
CREATE INDEX "idx_tts_venue_week" ON "tournament_team_scores" ("venue_id","week_id");
CREATE UNIQUE INDEX "tournament_team_scores_pkey" ON "tournament_team_scores" ("id");
CREATE UNIQUE INDEX "tournament_team_scores_tournament_team_id_venue_id_week_id_key" ON "tournament_team_scores" ("tournament_team_id","venue_id","week_id");
CREATE UNIQUE INDEX "tournament_teams_access_key_key" ON "tournament_teams" ("access_key");
CREATE UNIQUE INDEX "tournament_teams_name_key" ON "tournament_teams" ("name");
CREATE UNIQUE INDEX "tournament_teams_pkey" ON "tournament_teams" ("id");
CREATE UNIQUE INDEX "tournament_weeks_pkey" ON "tournament_weeks" ("id");
CREATE UNIQUE INDEX "tournament_weeks_week_ending_key" ON "tournament_weeks" ("week_ending");
CREATE UNIQUE INDEX "venues_access_key_key" ON "venues" ("access_key");
CREATE UNIQUE INDEX "venues_name_key" ON "venues" ("name");
CREATE UNIQUE INDEX "venues_pkey" ON "venues" ("id");
ALTER TABLE "venues" ADD CONSTRAINT "venues_default_host_id_fkey" FOREIGN KEY ("default_host_id") REFERENCES "hosts"("id") ON DELETE SET NULL;