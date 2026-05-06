import type {FocusEvent, JSX, ReactNode} from "react";
import {useEffect, useRef, useState} from "react";
import {Controller, useForm, type UseFormRegisterReturn} from "react-hook-form";
import {zodResolver} from "@hookform/resolvers/zod";
import {useQuery} from "@tanstack/react-query";
import {Check, CheckCircle2, Eye, EyeOff, LoaderCircle, X} from "lucide-react";
import {Link, useNavigate} from "react-router-dom";
import {toast} from "sonner";

import {Logo} from "../components/brand/Logo";
import {PageShell} from "../components/layout/PageShell";
import {Button} from "../components/ui/button";
import {Card} from "../components/ui/card";
import {EncryptedText} from "../components/ui/encrypted-text";
import {Input} from "../components/ui/input";
import {Label} from "../components/ui/label";
import {
  ApiError,
  checkUsernameAvailability,
  completeProfile,
  fetchRegisterOptions,
  registerStudent,
  resendVerificationEmail,
} from "../features/auth/api/auth";
import {AvatarUploadField, type AvatarUploadStatus} from "../features/auth/components/AvatarUploadField";
import {CountryDropdown} from "../features/auth/components/CountryDropdown";
import {DateOfBirthField} from "../features/auth/components/DateOfBirthField";
import {OptionDropdownField} from "../features/auth/components/OptionDropdownField";
import {createRegisterSchema, type RegisterFormValues} from "../features/auth/schemas/authSchemas";
import {useAuthStore} from "../features/auth/store/useAuthStore";
import {getDefaultAuthenticatedPath, isStudentProfileIncomplete} from "../features/auth/utils/routing";
import {cn} from "../lib/utils";

type AuthViewState = "auth" | "verification";
type UsernameState = "idle" | "checking" | "available" | "taken" | "error";

const GENDER_OPTIONS = [
  {label: "Male", value: "male"},
  {label: "Female", value: "female"},
  {label: "Other", value: "other"},
] as const;

const signUpHighlights = [
  "Use required-field onboarding for the MVP account flow",
  "Keep registration and profile completion on the same route contract",
  "Preserve backend-owned profile truth before students enter learning",
] as const;

const MARKETING_SITE_URL = "https://www.xoxoeducation.com/";

interface AuthScaffoldProps {
  readonly children: ReactNode;
  readonly description: string;
  readonly eyebrow: string;
  readonly highlights: readonly string[];
  readonly title: string;
}

function FieldLabel({
  children,
  htmlFor,
  required = false,
}: {
  readonly children: ReactNode;
  readonly htmlFor?: string;
  readonly required?: boolean;
}): JSX.Element {
  return (
    <Label className="flex items-center gap-1.5 text-sm font-medium text-foreground" htmlFor={htmlFor}>
      <span>{children}</span>
      {required && (
        <span aria-hidden="true" className="text-base leading-none text-destructive">
          *
        </span>
      )}
    </Label>
  );
}

function FieldBlock({
  children,
  error,
  label,
  required = false,
}: {
  readonly children: ReactNode;
  readonly error?: string;
  readonly label: ReactNode;
  readonly required?: boolean;
}): JSX.Element {
  return (
    <div className="space-y-2.5">
      <FieldLabel required={required}>{label}</FieldLabel>
      {children}
      {error && (
        <p className="text-xs text-destructive" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

function AuthScaffold({
  children,
  description,
  eyebrow,
  highlights,
  title,
}: AuthScaffoldProps): JSX.Element {
  return (
    <PageShell
      className="bg-background text-foreground"
      contentClassName="grid min-h-screen gap-10 py-8 lg:grid-cols-[minmax(0,0.95fr)_minmax(0,1.05fr)]"
      width="full"
    >
      <section className="flex flex-col justify-between gap-10 py-4">
        <div className="space-y-8">
          <a className="inline-flex items-center" href={MARKETING_SITE_URL}>
            <Logo height={40} />
          </a>

          <div className="space-y-4">
            <div className="inline-flex items-center rounded-[26px] bg-secondary px-3 py-1 text-[12px] font-medium text-secondary-foreground">
              {eyebrow}
            </div>
            <div className="space-y-3">
              <h1 className="max-w-xl text-4xl font-semibold tracking-[-0.025em] text-foreground sm:text-5xl">
                {title}
              </h1>
              <p className="max-w-xl text-[14px] leading-[1.43] text-muted-foreground sm:text-base">
                {description}
              </p>
            </div>
          </div>
        </div>

        <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-1">
          {highlights.map((highlight) => (
            <div className="rounded-xl border border-border bg-card p-4 text-sm leading-6 text-muted-foreground" key={highlight}>
              {highlight}
            </div>
          ))}
        </div>
      </section>

      <section className="flex items-center justify-center py-2 lg:py-8">
        <Card className="w-full max-w-2xl border-border bg-card p-5 sm:p-6">
          <div className="rounded-xl border border-border bg-background p-5 sm:p-6">{children}</div>
        </Card>
      </section>
    </PageShell>
  );
}

function LoadingAuthPage(): JSX.Element {
  return (
    <div className="space-y-2 text-center">
      <p className="text-xs font-semibold uppercase tracking-[0.24em] text-muted-foreground">Preparing</p>
      <p className="text-2xl font-semibold tracking-tight text-foreground">Loading session context…</p>
    </div>
  );
}

function normalizeUserGender(value: string | null | undefined): string {
  if (GENDER_OPTIONS.some((option) => option.value === value)) {
    return value as string;
  }
  return "";
}

function VerificationPrompt({email}: {readonly email: string}): JSX.Element {
  const [isResending, setIsResending] = useState(false);
  const [resent, setResent] = useState(false);

  const handleResend = async (): Promise<void> => {
    setIsResending(true);
    try {
      await resendVerificationEmail(email);
      setResent(true);
      toast.success("Verification email resent.");
    } catch (resendFailure) {
      toast.error(resendFailure instanceof Error ? resendFailure.message : "Verification email could not be resent.");
    } finally {
      setIsResending(false);
    }
  };

  return (
    <div className="space-y-5 text-center">
      <div className="mx-auto flex size-14 items-center justify-center rounded-full border border-border/70 bg-background shadow-sm">
        <CheckCircle2 className="size-7 text-foreground" strokeWidth={1.7} />
      </div>
      <div className="space-y-2">
        <p className="text-xs font-semibold uppercase tracking-[0.24em] text-muted-foreground">Verify Email</p>
        <h1 className="text-3xl font-semibold tracking-tight text-foreground">Check your inbox</h1>
        <p className="text-sm leading-6 text-muted-foreground">
          We sent a verification link to <span className="font-medium text-foreground">{email}</span>. Confirm your
          email before signing in.
        </p>
      </div>
      <div className="space-y-3">
        <Button className="w-full" disabled={isResending || resent} onClick={() => void handleResend()} type="button" variant="outline">
          {isResending ? "Resending…" : resent ? "Email resent" : "Resend verification email"}
        </Button>
        <Link
          className="inline-block text-sm text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
          to="/sign-in"
        >
          Back to sign in
        </Link>
      </div>
    </div>
  );
}

interface EncryptedInputFieldProps {
  readonly afterBlur?: () => void;
  readonly autoComplete?: string;
  readonly autoFocus?: boolean;
  readonly disabled?: boolean;
  readonly error?: string;
  readonly id: string;
  readonly inputClassName?: string;
  readonly label: string;
  readonly readOnly?: boolean;
  readonly registration: UseFormRegisterReturn;
  readonly required?: boolean;
  readonly trailing?: ReactNode;
  readonly type?: string;
  readonly value: string;
}

function EncryptedInputField({
  afterBlur,
  autoComplete,
  autoFocus = false,
  disabled = false,
  error,
  id,
  inputClassName,
  label,
  readOnly = false,
  registration,
  required = false,
  trailing,
  type = "text",
  value,
}: EncryptedInputFieldProps): JSX.Element {
  const [isFocused, setIsFocused] = useState(false);
  const overlayKeyRef = useRef(0);
  const overlayWasHiddenRef = useRef(false);
  const showOverlay = !value && !isFocused;

  if (!showOverlay) {
    overlayWasHiddenRef.current = true;
  } else if (overlayWasHiddenRef.current) {
    overlayKeyRef.current += 1;
    overlayWasHiddenRef.current = false;
  }

  const handleBlur = (event: FocusEvent<HTMLInputElement>): void => {
    registration.onBlur(event);
    setIsFocused(false);
    afterBlur?.();
  };

  return (
    <FieldBlock error={error} label={label} required={required}>
      <div className="relative">
        {showOverlay && (
          <div className="pointer-events-none absolute inset-0 flex items-center px-3">
            <EncryptedText
              encryptedClassName="text-muted-foreground/40"
              key={overlayKeyRef.current}
              revealDelayMs={40}
              revealedClassName="text-muted-foreground"
              text={label}
            />
          </div>
        )}

        <Input
          {...registration}
          aria-invalid={error ? "true" : undefined}
          aria-label={label}
          aria-required={required ? "true" : undefined}
          autoComplete={autoComplete}
          autoFocus={autoFocus}
          className={cn(
            "h-12 rounded-md border-border bg-background placeholder:text-transparent",
            trailing && "pr-10",
            readOnly && "bg-muted text-muted-foreground",
            error && "border-destructive",
            inputClassName,
          )}
          disabled={disabled}
          id={id}
          onBlur={handleBlur}
          onFocus={() => setIsFocused(true)}
          readOnly={readOnly}
          type={type}
        />

        {trailing && <div className="absolute right-3 top-1/2 -translate-y-1/2">{trailing}</div>}
      </div>
    </FieldBlock>
  );
}

function SignupPanel({isCompletionMode}: {readonly isCompletionMode: boolean}): JSX.Element {
  const navigate = useNavigate();
  const setUser = useAuthStore((state) => state.setUser);
  const user = useAuthStore((state) => state.user);
  const [viewState, setViewState] = useState<AuthViewState>("auth");
  const [submittedEmail, setSubmittedEmail] = useState("");
  const [serverError, setServerError] = useState<string | null>(null);
  const [avatarUploadStatus, setAvatarUploadStatus] = useState<AvatarUploadStatus>(isCompletionMode ? "uploaded" : "idle");
  const [usernameState, setUsernameState] = useState<UsernameState>("idle");
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);

  const registerSchema = createRegisterSchema({requirePassword: !isCompletionMode});
  const {
    clearErrors,
    control,
    formState: {errors, isSubmitting},
    handleSubmit,
    register,
    reset,
    setError,
    setValue,
    watch,
  } = useForm<RegisterFormValues>({
    resolver: zodResolver(registerSchema),
    defaultValues: {
      avatarUrl: "",
      confirmPassword: "",
      country: "",
      dateOfBirth: "",
      displayName: "",
      email: "",
      gender: "",
      password: "",
      socialLinks: {
        instagram: "",
        linkedin: "",
        tiktok: "",
        website: "",
      },
      username: "",
    },
  });

  const registerOptionsQuery = useQuery({
    queryFn: fetchRegisterOptions,
    queryKey: ["register-options"],
    retry: 1,
  });

  useEffect(() => {
    if (!registerOptionsQuery.data) {
      return;
    }

    reset({
      avatarUrl: user?.avatar_url ?? "",
      confirmPassword: "",
      country: user?.country ?? "",
      dateOfBirth: user?.date_of_birth ?? "",
      displayName: user?.display_name ?? "",
      email: user?.email ?? "",
      gender: normalizeUserGender(user?.gender),
      password: "",
      socialLinks: {
        instagram: "",
        linkedin: "",
        tiktok: "",
        website: "",
      },
      username: user?.username ?? "",
    });
    setAvatarUploadStatus(user?.avatar_url ? "uploaded" : "idle");
  }, [registerOptionsQuery.data, reset, user]);

  const displayNameValue = watch("displayName") ?? "";
  const usernameValue = watch("username") ?? "";
  const emailValue = watch("email") ?? "";
  const passwordValue = watch("password") ?? "";
  const confirmPasswordValue = watch("confirmPassword") ?? "";
  const avatarUrlValue = watch("avatarUrl") ?? "";
  const previousUsernameValueRef = useRef(usernameValue);

  useEffect(() => {
    if (previousUsernameValueRef.current === usernameValue) {
      return;
    }

    previousUsernameValueRef.current = usernameValue;
    setServerError(null);
    setUsernameState("idle");
    if (errors.username && usernameValue.trim().length > 0) {
      clearErrors("username");
    }
  }, [clearErrors, errors.username, usernameValue]);

  if (!isCompletionMode && viewState === "verification") {
    return <VerificationPrompt email={submittedEmail} />;
  }

  if (registerOptionsQuery.isLoading) {
    return <LoadingAuthPage />;
  }

  if (!registerOptionsQuery.data) {
    return (
      <div className="space-y-4 text-center">
        <div className="space-y-2">
          <p className="text-xs font-semibold uppercase tracking-[0.24em] text-muted-foreground">Unavailable</p>
          <h1 className="text-2xl font-semibold tracking-tight text-foreground">Registration options failed to load</h1>
          <p className="text-sm text-muted-foreground">Try again to fetch the required onboarding configuration.</p>
        </div>
        <Button className="w-full" onClick={() => void registerOptionsQuery.refetch()} type="button">
          Retry
        </Button>
      </div>
    );
  }

  const handleUsernameBlur = async (): Promise<void> => {
    const normalizedUsername = usernameValue.trim().toLowerCase();
    if (normalizedUsername.length < 3 || !/^[a-z0-9_]+$/.test(normalizedUsername)) {
      setUsernameState("idle");
      return;
    }

    if (isCompletionMode && normalizedUsername === (user?.username ?? "").trim().toLowerCase()) {
      setUsernameState("idle");
      return;
    }

    setUsernameState("checking");

    try {
      const result = await checkUsernameAvailability(normalizedUsername);
      setUsernameState(result.available ? "available" : "taken");
      if (!result.available) {
        setError("username", {message: "This username is already taken", type: "manual"});
      }
    } catch {
      setUsernameState("error");
    }
  };

  const onSubmit = async (values: RegisterFormValues): Promise<void> => {
    setServerError(null);

    if (avatarUploadStatus !== "uploaded") {
      setError("avatarUrl", {message: "Upload an avatar before continuing", type: "manual"});
      return;
    }

    const payload = {
      avatar_url: values.avatarUrl,
      country: values.country,
      date_of_birth: values.dateOfBirth,
      display_name: values.displayName.trim(),
      gender: values.gender,
      username: values.username.trim().toLowerCase(),
    };

    try {
      if (isCompletionMode) {
        const updatedUser = await completeProfile(payload);
        setUser(updatedUser);
        toast.success("Profile completed.");
        navigate(getDefaultAuthenticatedPath({...updatedUser, profile_complete: true}), {replace: true});
        return;
      }

      await registerStudent({
        ...payload,
        email: values.email.trim(),
        password: values.password ?? "",
      });
      setSubmittedEmail(values.email.trim());
      setViewState("verification");
    } catch (submitFailure) {
      if (submitFailure instanceof ApiError) {
        if (submitFailure.code === "USERNAME_ALREADY_TAKEN") {
          setError("username", {message: "This username is already taken", type: "server"});
          setUsernameState("taken");
          return;
        }

        if (submitFailure.code === "EMAIL_ALREADY_REGISTERED") {
          setError("email", {message: "This email is already registered", type: "server"});
          return;
        }

        setServerError(submitFailure.message);
        return;
      }

      setServerError("Something went wrong. Please try again.");
    }
  };

  const usernameReg = register("username");
  const usernameHasPositiveState = !errors.username && usernameState === "available";
  const usernameHasNegativeState = Boolean(errors.username) || usernameState === "taken";
  const usernameStatusAdornment =
    usernameState === "checking" ? (
      <LoaderCircle className="size-4 animate-spin text-muted-foreground" />
    ) : usernameHasPositiveState ? (
      <Check className="size-4 text-emerald-500" />
    ) : usernameHasNegativeState ? (
      <X className="size-4 text-destructive" />
    ) : null;

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <p className="text-xs font-semibold uppercase tracking-[0.24em] text-muted-foreground">
          {isCompletionMode ? "Complete Profile" : "Sign Up"}
        </p>
        <h1 className="text-3xl font-semibold tracking-tight text-foreground">
          {isCompletionMode ? "Finish your onboarding details" : "Create your account"}
        </h1>
        <p className="text-sm leading-6 text-muted-foreground">
          {isCompletionMode
            ? "We only need the required fields before you can continue into the student experience."
            : "For this MVP, account creation uses required fields only. Fill in every marked field to get started."}
        </p>
      </div>

      <form className="space-y-4" noValidate onSubmit={handleSubmit(onSubmit)}>
        <EncryptedInputField
          autoComplete="name"
          autoFocus={!isCompletionMode}
          error={errors.displayName?.message}
          id="signup-display-name"
          label="Full name"
          registration={register("displayName")}
          required
          value={displayNameValue}
        />

        <EncryptedInputField
          afterBlur={() => void handleUsernameBlur()}
          autoComplete="username"
          error={errors.username?.message}
          id="signup-username"
          inputClassName={cn(
            usernameHasPositiveState && "border-emerald-500 focus-visible:border-emerald-500 focus-visible:ring-emerald-500/20",
            usernameHasNegativeState && "border-destructive",
          )}
          label="Username"
          registration={usernameReg}
          required
          trailing={usernameStatusAdornment}
          value={usernameValue}
        />

        <EncryptedInputField
          autoComplete="email"
          error={errors.email?.message}
          id="signup-email"
          label="Email"
          readOnly={isCompletionMode}
          registration={register("email")}
          required
          value={emailValue}
        />

        {!isCompletionMode && (
          <>
            <EncryptedInputField
              autoComplete="new-password"
              error={errors.password?.message}
              id="signup-password"
              label="Password"
              registration={register("password")}
              required
              trailing={
                <button
                  aria-label={showPassword ? "Hide password" : "Show password"}
                  className="flex size-8 items-center justify-center text-muted-foreground hover:text-foreground"
                  onClick={() => setShowPassword((current) => !current)}
                  type="button"
                >
                  {showPassword ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
                </button>
              }
              type={showPassword ? "text" : "password"}
              value={passwordValue}
            />

            <EncryptedInputField
              autoComplete="new-password"
              error={errors.confirmPassword?.message}
              id="signup-confirm-password"
              label="Confirm password"
              registration={register("confirmPassword")}
              required
              trailing={
                <button
                  aria-label={showConfirmPassword ? "Hide confirm password" : "Show confirm password"}
                  className="flex size-8 items-center justify-center text-muted-foreground hover:text-foreground"
                  onClick={() => setShowConfirmPassword((current) => !current)}
                  type="button"
                >
                  {showConfirmPassword ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
                </button>
              }
              type={showConfirmPassword ? "text" : "password"}
              value={confirmPasswordValue}
            />
          </>
        )}

        <FieldBlock error={errors.dateOfBirth?.message} label="Date of birth" required>
          <Controller
            control={control}
            name="dateOfBirth"
            render={({field}) => (
              <DateOfBirthField error={errors.dateOfBirth?.message} onChange={field.onChange} value={field.value} />
            )}
          />
        </FieldBlock>

        <FieldBlock error={errors.country?.message} label="Country" required>
          <Controller
            control={control}
            name="country"
            render={({field}) => (
              <CountryDropdown
                error={errors.country?.message}
                onChange={field.onChange}
                options={registerOptionsQuery.data.countries}
                value={field.value}
              />
            )}
          />
        </FieldBlock>

        <FieldBlock error={errors.gender?.message} label="Gender" required>
          <Controller
            control={control}
            name="gender"
            render={({field}) => (
              <OptionDropdownField
                ariaLabel="Gender"
                error={errors.gender?.message}
                onChange={field.onChange}
                options={GENDER_OPTIONS}
                placeholder="Select a gender"
                value={field.value}
              />
            )}
          />
        </FieldBlock>

        <div className="space-y-2.5">
          <FieldLabel required>Profile photo</FieldLabel>
          <AvatarUploadField
            acceptedMimeTypes={registerOptionsQuery.data.avatar_constraints.accepted_mime_types}
            error={errors.avatarUrl?.message}
            maxFileSizeBytes={registerOptionsQuery.data.avatar_constraints.max_file_size_bytes}
            onChange={(publicUrl) => setValue("avatarUrl", publicUrl, {shouldDirty: true, shouldValidate: true})}
            onStatusChange={setAvatarUploadStatus}
            value={avatarUrlValue}
          />
        </div>

        {serverError && (
          <p className="text-sm text-destructive" role="alert">
            {serverError}
          </p>
        )}

        <Button className="h-12 w-full" disabled={isSubmitting} type="submit">
          {isSubmitting
            ? isCompletionMode
              ? "Saving…"
              : "Creating account…"
            : isCompletionMode
              ? "Save and continue"
              : "Create account"}
        </Button>

        {!isCompletionMode ? (
          <p className="text-sm text-muted-foreground">
            Already have an account?{" "}
            <Link className="text-foreground underline-offset-4 hover:underline" to="/sign-in">
              Sign in
            </Link>
            .
          </p>
        ) : null}
      </form>
    </div>
  );
}

export function SignUpPage(): JSX.Element {
  const navigate = useNavigate();
  const status = useAuthStore((state) => state.status);
  const user = useAuthStore((state) => state.user);
  const isCompletionMode = status === "authenticated" && isStudentProfileIncomplete(user);

  useEffect(() => {
    if (status === "authenticated" && user && !isStudentProfileIncomplete(user)) {
      navigate(getDefaultAuthenticatedPath(user), {replace: true});
    }
  }, [navigate, status, user]);

  return (
    <AuthScaffold
      description="Create an account with the required onboarding profile fields only. If a student signed in before completing their profile, this route also owns the completion step."
      eyebrow={isCompletionMode ? "Complete Profile" : "Sign Up"}
      highlights={signUpHighlights}
      title="Start with the required profile data, then move into placement and learning."
    >
      {(status === "idle" || status === "loading") && <LoadingAuthPage />}
      {status === "anonymous" && <SignupPanel isCompletionMode={false} />}
      {status !== "idle" && status !== "loading" && isCompletionMode && <SignupPanel isCompletionMode />}
      {status === "authenticated" && user && !isCompletionMode && <LoadingAuthPage />}
    </AuthScaffold>
  );
}
