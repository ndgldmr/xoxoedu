import type {ChangeEvent, JSX} from "react";
import {useEffect, useRef, useState} from "react";
import {ImagePlus, LoaderCircle, RefreshCcw, Upload} from "lucide-react";

import {uploadAvatar} from "../api/auth";
import {Button} from "../../../components/ui/button";
import {cn} from "../../../lib/utils";

export type AvatarUploadStatus = "idle" | "uploading" | "uploaded" | "error";

interface AvatarUploadFieldProps {
  readonly acceptedMimeTypes: string[];
  readonly disabled?: boolean;
  readonly error?: string;
  readonly maxFileSizeBytes: number;
  readonly onChange: (value: string) => void;
  readonly onStatusChange: (status: AvatarUploadStatus) => void;
  readonly value: string;
}

function formatFileSize(bytes: number): string {
  return `${Math.round((bytes / (1024 * 1024)) * 10) / 10} MB`;
}

export function AvatarUploadField({
  acceptedMimeTypes,
  disabled = false,
  error,
  maxFileSizeBytes,
  onChange,
  onStatusChange,
  value,
}: AvatarUploadFieldProps): JSX.Element {
  const [previewUrl, setPreviewUrl] = useState<string | null>(value || null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [status, setStatus] = useState<AvatarUploadStatus>(value ? "uploaded" : "idle");
  const inputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    onStatusChange(status);
  }, [onStatusChange, status]);

  useEffect(() => {
    if (!value && status === "uploaded") {
      setStatus("idle");
      setPreviewUrl(null);
    }
  }, [status, value]);

  const handleChooseFile = (): void => {
    inputRef.current?.click();
  };

  const handleFileChange = async (event: ChangeEvent<HTMLInputElement>): Promise<void> => {
    const file = event.target.files?.[0];
    if (!file) {
      return;
    }

    setUploadError(null);

    if (!acceptedMimeTypes.includes(file.type)) {
      setStatus("error");
      setUploadError("Choose a JPEG, PNG, or WebP image.");
      return;
    }

    if (file.size > maxFileSizeBytes) {
      setStatus("error");
      setUploadError(`Avatar must be ${formatFileSize(maxFileSizeBytes)} or smaller.`);
      return;
    }

    const localPreviewUrl = URL.createObjectURL(file);
    setPreviewUrl(localPreviewUrl);
    setStatus("uploading");

    try {
      const publicUrl = await uploadAvatar(file);
      onChange(publicUrl);
      setPreviewUrl(publicUrl);
      setStatus("uploaded");
    } catch (uploadFailure) {
      setStatus("error");
      setUploadError(uploadFailure instanceof Error ? uploadFailure.message : "Avatar upload failed.");
    } finally {
      URL.revokeObjectURL(localPreviewUrl);
      event.target.value = "";
    }
  };

  return (
    <div className="space-y-3">
      <input
        accept={acceptedMimeTypes.join(",")}
        className="hidden"
        disabled={disabled}
        onChange={(event) => void handleFileChange(event)}
        ref={inputRef}
        type="file"
      />

      <div
        className={cn(
          "flex items-center gap-4 rounded-xl border border-border bg-muted/20 p-4",
          (error || uploadError) && "border-destructive/60",
        )}
      >
        <div className="flex h-20 w-20 shrink-0 items-center justify-center overflow-hidden rounded-full border border-border bg-background">
          {previewUrl ? (
            <img alt="Avatar preview" className="h-full w-full object-cover" src={previewUrl} />
          ) : (
            <ImagePlus className="size-8 text-muted-foreground" />
          )}
        </div>

        <div className="min-w-0 flex-1 space-y-1">
          <p className="text-sm font-medium text-foreground">Profile photo</p>
          <p className="text-sm text-muted-foreground">
            Upload a JPEG, PNG, or WebP image up to {formatFileSize(maxFileSizeBytes)}.
          </p>
          {status === "uploading" && (
            <p className="flex items-center gap-2 text-sm text-foreground">
              <LoaderCircle className="size-4 animate-spin" />
              Uploading avatar…
            </p>
          )}
          {status === "uploaded" && (
            <p className="text-sm text-foreground">Avatar uploaded successfully.</p>
          )}
          {(error || uploadError) && (
            <p className="text-sm text-destructive" role="alert">
              {uploadError ?? error}
            </p>
          )}
        </div>

        <div className="flex shrink-0 flex-col gap-2">
          <Button disabled={disabled || status === "uploading"} onClick={handleChooseFile} type="button" variant="outline">
            {status === "uploaded" ? (
              <>
                <RefreshCcw className="size-4" />
                Replace
              </>
            ) : (
              <>
                <Upload className="size-4" />
                Upload
              </>
            )}
          </Button>
        </div>
      </div>
    </div>
  );
}
