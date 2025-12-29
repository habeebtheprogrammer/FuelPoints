CREATE TABLE "admin_users" (
	"id" serial PRIMARY KEY NOT NULL,
	"first_name" varchar(100) NOT NULL,
	"last_name" varchar(100) NOT NULL,
	"email" varchar(255) NOT NULL,
	"phone" varchar(20) NOT NULL,
	"password" varchar(255) NOT NULL,
	"created_at" timestamp DEFAULT now() NOT NULL,
	CONSTRAINT "admin_users_email_unique" UNIQUE("email")
);
--> statement-breakpoint
CREATE TABLE "item_group_upcs" (
	"id" serial PRIMARY KEY NOT NULL,
	"item_group_id" integer NOT NULL,
	"upc" varchar(50) NOT NULL,
	"created_at" timestamp DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "item_groups" (
	"id" serial PRIMARY KEY NOT NULL,
	"name" varchar(255) NOT NULL,
	"description" text,
	"created_at" timestamp DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "locations" (
	"id" serial PRIMARY KEY NOT NULL,
	"location_name" varchar(255) NOT NULL,
	"pdi_store_number" varchar(50) NOT NULL,
	"pos_id" varchar(50),
	"address_1" varchar(255) NOT NULL,
	"address_2" varchar(255),
	"city" varchar(100) NOT NULL,
	"state" varchar(50) NOT NULL,
	"zip_code" varchar(20) NOT NULL,
	"pos_type" varchar(50) NOT NULL,
	"created_at" timestamp DEFAULT now() NOT NULL,
	CONSTRAINT "locations_pdi_store_number_unique" UNIQUE("pdi_store_number")
);
--> statement-breakpoint
CREATE TABLE "pos_presence" (
	"id" serial PRIMARY KEY NOT NULL,
	"location_id" integer,
	"pdi_store_number" varchar(50) NOT NULL,
	"pos_id" varchar(50),
	"pos_type" varchar(50) NOT NULL,
	"pos_ip_address" varchar(50),
	"edge_ip_address" varchar(50),
	"edge_version" varchar(50),
	"status" varchar(20) DEFAULT 'online' NOT NULL,
	"last_seen" timestamp DEFAULT now() NOT NULL,
	"created_at" timestamp DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "pricebook" (
	"id" serial PRIMARY KEY NOT NULL,
	"upc" varchar(50) NOT NULL,
	"description" varchar(255) NOT NULL,
	"sku" varchar(50),
	"unit" varchar(20),
	"price" numeric(10, 2),
	"category" varchar(50),
	"created_at" timestamp DEFAULT now() NOT NULL,
	CONSTRAINT "pricebook_upc_unique" UNIQUE("upc")
);
--> statement-breakpoint
CREATE TABLE "promotion_locations" (
	"id" serial PRIMARY KEY NOT NULL,
	"promotion_id" integer NOT NULL,
	"location_id" integer NOT NULL,
	"created_at" timestamp DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "promotions" (
	"id" serial PRIMARY KEY NOT NULL,
	"item_group_id" integer NOT NULL,
	"quantity" integer NOT NULL,
	"discount_type" varchar(20) DEFAULT 'multipack' NOT NULL,
	"price" numeric(10, 2),
	"amount_off" numeric(10, 2),
	"requires_loyalty_id" boolean DEFAULT false NOT NULL,
	"is_active" boolean DEFAULT true NOT NULL,
	"start_date" timestamp,
	"end_date" timestamp,
	"created_at" timestamp DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "rewards" (
	"id" serial PRIMARY KEY NOT NULL,
	"user_id" integer NOT NULL,
	"points" integer DEFAULT 0 NOT NULL,
	"updated_at" timestamp DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "transactions" (
	"id" serial PRIMARY KEY NOT NULL,
	"user_id" integer NOT NULL,
	"points" integer NOT NULL,
	"description" text NOT NULL,
	"created_at" timestamp DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "users" (
	"id" serial PRIMARY KEY NOT NULL,
	"first_name" varchar(100) NOT NULL,
	"last_name" varchar(100) NOT NULL,
	"email" varchar(255) NOT NULL,
	"phone" varchar(20) NOT NULL,
	"date_of_birth" varchar(20) NOT NULL,
	"password" varchar(255) NOT NULL,
	"account_number" varchar(18) NOT NULL,
	"loyalty_id" varchar(22) NOT NULL,
	"created_at" timestamp DEFAULT now() NOT NULL,
	CONSTRAINT "users_email_unique" UNIQUE("email"),
	CONSTRAINT "users_account_number_unique" UNIQUE("account_number"),
	CONSTRAINT "users_loyalty_id_unique" UNIQUE("loyalty_id")
);
--> statement-breakpoint
ALTER TABLE "item_group_upcs" ADD CONSTRAINT "item_group_upcs_item_group_id_item_groups_id_fk" FOREIGN KEY ("item_group_id") REFERENCES "public"."item_groups"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "pos_presence" ADD CONSTRAINT "pos_presence_location_id_locations_id_fk" FOREIGN KEY ("location_id") REFERENCES "public"."locations"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "promotion_locations" ADD CONSTRAINT "promotion_locations_promotion_id_promotions_id_fk" FOREIGN KEY ("promotion_id") REFERENCES "public"."promotions"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "promotion_locations" ADD CONSTRAINT "promotion_locations_location_id_locations_id_fk" FOREIGN KEY ("location_id") REFERENCES "public"."locations"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "promotions" ADD CONSTRAINT "promotions_item_group_id_item_groups_id_fk" FOREIGN KEY ("item_group_id") REFERENCES "public"."item_groups"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "rewards" ADD CONSTRAINT "rewards_user_id_users_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."users"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "transactions" ADD CONSTRAINT "transactions_user_id_users_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."users"("id") ON DELETE no action ON UPDATE no action;