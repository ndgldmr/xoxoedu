import {z} from "zod";

export const loginSchema = z.object({
  email: z.string().min(1, "Email is required").email("Enter a valid email address"),
  password: z.string().min(1, "Password is required"),
});

export type LoginFormValues = z.infer<typeof loginSchema>;

export const forgotPasswordSchema = z.object({
  email: z.string().min(1, "Email is required").email("Enter a valid email address"),
});

export type ForgotPasswordFormValues = z.infer<typeof forgotPasswordSchema>;

export const resetPasswordSchema = z
  .object({
    password: z
      .string()
      .min(8, "Password must be at least 8 characters")
      .max(128, "Password must be 128 characters or fewer"),
    confirmPassword: z.string().min(1, "Please confirm your password"),
  })
  .refine((d) => d.password === d.confirmPassword, {
    message: "Passwords do not match",
    path: ["confirmPassword"],
  });

export type ResetPasswordFormValues = z.infer<typeof resetPasswordSchema>;

const socialLinkSchema = z
  .string()
  .trim()
  .url("Enter a valid URL starting with http:// or https://")
  .or(z.literal(""))
  .transform((value) => value.trim());

export function createRegisterSchema(options: {readonly requirePassword: boolean}) {
  const passwordField = options.requirePassword
    ? z
        .string()
        .min(8, "Password must be at least 8 characters")
        .max(128, "Password must be 128 characters or fewer")
    : z.string().optional();

  return z
    .object({
      avatarUrl: z.string().min(1, "Avatar is required"),
      country: z.string().min(1, "Country is required"),
      dateOfBirth: z.string().min(1, "Date of birth is required"),
      displayName: z.string().trim().min(1, "Full name is required").max(100, "Full name is too long"),
      email: z.string().trim().min(1, "Email is required").email("Enter a valid email address"),
      gender: z
        .string()
        .min(1, "Gender is required")
        .refine((value) => ["male", "female", "other"].includes(value), "Select a valid gender option"),
      password: passwordField,
      confirmPassword: options.requirePassword
        ? z.string().min(1, "Please confirm your password")
        : z.string().optional(),
      socialLinks: z.object({
        instagram: socialLinkSchema.optional(),
        linkedin: socialLinkSchema.optional(),
        tiktok: socialLinkSchema.optional(),
        website: socialLinkSchema.optional(),
      }),
      username: z
        .string()
        .trim()
        .min(3, "Username must be at least 3 characters")
        .max(50, "Username must be 50 characters or fewer")
        .regex(/^[a-z0-9_]+$/, "Use lowercase letters, numbers, and underscores only"),
    })
    .superRefine((values, context) => {
      const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(values.dateOfBirth);
      const date = match
        ? new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]))
        : new Date(Number.NaN);
      const today = new Date();
      const currentDate = new Date(today.getFullYear(), today.getMonth(), today.getDate());
      if (Number.isNaN(date.getTime()) || date >= currentDate) {
        context.addIssue({
          code: z.ZodIssueCode.custom,
          message: "Date of birth must be in the past",
          path: ["dateOfBirth"],
        });
      }

      if (options.requirePassword && values.password !== values.confirmPassword) {
        context.addIssue({
          code: z.ZodIssueCode.custom,
          message: "Passwords do not match",
          path: ["confirmPassword"],
        });
      }
    });
}

export type RegisterFormValues = z.infer<ReturnType<typeof createRegisterSchema>>;
