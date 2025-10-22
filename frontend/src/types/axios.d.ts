import "axios";

declare module "axios" {
  export interface AxiosRequestConfig {
    /** internal flag set by our interceptor to avoid infinite loops */
    _retry?: boolean;
  }
}
